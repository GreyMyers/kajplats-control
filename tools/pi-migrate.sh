#!/usr/bin/env bash
# Run this ON THE LAPTOP, after tools/pi-setup.sh has finished on the Pi.
#
# Moves the Thread network and the Matter fabric to the Pi. The important part
# is the matter-server storage directory: it holds the fabric's operational
# credentials and each commissioned node, so copying it means the bulbs stay
# paired. Forming a fresh fabric on the Pi instead would orphan both bulbs and
# require a factory reset and re-commissioning of each.
#
#   tools/pi-migrate.sh pi@raspberrypi.local
#
# The laptop's own services are stopped first and left disabled: two
# controllers sharing one fabric identity on the same Thread network will
# fight over the nodes.

set -euo pipefail

TARGET="${1:-}"
[[ -n "$TARGET" ]] || { echo "usage: $0 <user@pi-host>" >&2; exit 1; }
[[ "$TARGET" == *@* ]] || TARGET="pi@$TARGET"

LOCAL_STORAGE="$HOME/.local/share/matter-server"
DATASET_FILE="$LOCAL_STORAGE/thread-dataset.hex"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

say "Checking the Pi is reachable"
ssh -o ConnectTimeout=10 "$TARGET" true
REMOTE_USER="${TARGET%@*}"
REMOTE_STORAGE="/home/$REMOTE_USER/.local/share/matter-server"
ssh "$TARGET" "test -f /etc/systemd/system/matter-server.service" \
    || { echo "pi-setup.sh has not been run on $TARGET yet" >&2; exit 1; }

say "Capturing the current Thread dataset"
if [[ -f "$DATASET_FILE" ]]; then
    echo "   using saved $DATASET_FILE"
else
    echo "   reading it from the running border router (needs sudo)"
    sudo ot-ctl dataset active -x | head -1 | tr -d '\r' > "$DATASET_FILE"
    chmod 600 "$DATASET_FILE"
fi
grep -qE '^[0-9a-fA-F]{40,}$' "$DATASET_FILE" \
    || { echo "dataset file does not look like hex; aborting" >&2; exit 1; }
echo "   dataset: $(wc -c < "$DATASET_FILE") bytes"

say "Stopping the laptop's border router and controller"
# Both must be down before the copy, so matter-server is not mid-write, and
# must stay down afterwards so the two hosts do not both drive the fabric.
sudo systemctl disable --now matter-server otbr-agent 2>/dev/null || true
sleep 2

say "Copying the Matter fabric and Thread dataset to the Pi"
ssh "$TARGET" "sudo systemctl stop matter-server otbr-agent 2>/dev/null || true; mkdir -p $REMOTE_STORAGE"
# Exclude lock/pid files: they refer to processes on this machine.
rsync -a --delete \
    --exclude 'matter.lock' --exclude 'matter.pid' --exclude 'server.log' \
    "$LOCAL_STORAGE"/ "$TARGET:$REMOTE_STORAGE"/
echo "   copied $(du -sh "$LOCAL_STORAGE" | cut -f1)"

say "Starting the border router on the Pi"
ssh "$TARGET" "sudo systemctl start otbr-agent"
sleep 8

say "Applying the Thread dataset on the Pi"
DATASET=$(cat "$DATASET_FILE")
ssh "$TARGET" "sudo ot-ctl dataset set active $DATASET \
    && sudo ot-ctl ifconfig up \
    && sudo ot-ctl thread start" >/dev/null
echo "   waiting for the mesh to form..."
for _ in $(seq 1 30); do
    STATE=$(ssh "$TARGET" "sudo ot-ctl state" 2>/dev/null | head -1 | tr -d '\r')
    case "$STATE" in
        leader|router|child) break ;;
    esac
    sleep 2
done
echo "   thread state: ${STATE:-unknown}"
[[ "$STATE" =~ ^(leader|router|child)$ ]] \
    || { echo "mesh did not form; check: ssh $TARGET sudo journalctl -u otbr-agent -n 40" >&2; exit 1; }

say "Starting matter-server on the Pi"
ssh "$TARGET" "sudo systemctl start matter-server"
sleep 15
ssh "$TARGET" "systemctl is-active matter-server"

cat <<EOF

$(say "Migrated")
The Pi now owns the Thread network and the Matter fabric. Your bulbs should
rejoin within a minute or two - they keep their commissioning.

The laptop's otbr-agent and matter-server are stopped and disabled. Unplug the
ESP32-C6 from the laptop and plug it into the Pi.

To use the GUI, open the tunnel and run the app:

    ssh -N -L 5580:localhost:5580 $TARGET &
    cd ~/kajplats && uv run kajplats --matter

Nothing is exposed on the building network: matter-server listens only on the
Pi's loopback, and the tunnel carries it to yours.
EOF
