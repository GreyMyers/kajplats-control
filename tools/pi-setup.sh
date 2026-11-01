#!/usr/bin/env bash
# Run this ON the Raspberry Pi. Installs a self-contained Thread border router
# + Matter controller, so that Matter's mDNS discovery never has to cross the
# network.
#
# That co-location is the whole point: this apartment's AP filters mDNS
# between clients, so a border router on one device cannot be discovered by a
# controller on another. Putting otbr-agent and matter-server on the same host
# keeps discovery on loopback, where nothing can filter it.
#
#   curl/scp this file to the Pi, then:  sudo bash pi-setup.sh
#
# Afterwards run tools/pi-migrate.sh on the laptop to move the existing Thread
# dataset and Matter fabric across, so the bulbs do not need re-pairing.

set -euo pipefail

NODE_MAJOR=22
OTBR_SRC=/opt/ot-br-posix
MATTER_DIR=/opt/matter-server
MATTER_USER="${SUDO_USER:-pi}"
MATTER_HOME="$(getent passwd "$MATTER_USER" | cut -d: -f6)"
STORAGE="$MATTER_HOME/.local/share/matter-server"

say()  { printf '\n\033[1m== %s\033[0m\n' "$1"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$1"; }

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

say "Sanity checks"
ARCH=$(dpkg --print-architecture)
echo "   arch: $ARCH   user: $MATTER_USER"
if [[ "$ARCH" != "arm64" && "$ARCH" != "amd64" ]]; then
    warn "32-bit OS detected. Node $NODE_MAJOR armv7 builds exist but are less"
    warn "well tested; a 64-bit Pi OS is strongly preferred."
fi
TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
echo "   RAM: ${TOTAL_MB} MB"
if (( TOTAL_MB < 900 )); then
    warn "Under ~1 GB (Pi Zero 2 W territory). Enabling zram below; expect"
    warn "matter-server to be the memory hog. Keep the Pi headless."
fi
if [[ ! -e /dev/ttyACM0 ]]; then
    warn "/dev/ttyACM0 not present - plug the ESP32-C6 (RCP firmware) in."
fi

say "Base packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
    git ca-certificates curl build-essential ninja-build cmake \
    avahi-daemon avahi-utils libavahi-client-dev ipset iproute2 \
    rsync zram-tools

say "Low-memory safety net (zram)"
# matter-server's peak is during the initial attribute read of each node.
# A compressed swap device costs almost nothing and avoids the OOM killer.
sed -i 's/^#\?ALGO=.*/ALGO=zstd/; s/^#\?PERCENT=.*/PERCENT=60/' /etc/default/zramswap || true
systemctl enable --now zramswap || warn "zram not enabled; continuing"

say "IPv6 forwarding + mDNS"
cat > /etc/sysctl.d/99-thread.conf <<'EOF'
net.ipv6.conf.all.forwarding=1
EOF
sysctl -q -w net.ipv6.conf.all.forwarding=1
systemctl enable --now avahi-daemon

say "Thread border router (ot-br-posix)"
if command -v otbr-agent >/dev/null; then
    echo "   already installed, skipping build"
else
    INFRA_IF=$(ip -o route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)
    echo "   infrastructure interface: ${INFRA_IF:-unknown}"
    [[ -d "$OTBR_SRC" ]] || git clone --depth 1 https://github.com/openthread/ot-br-posix "$OTBR_SRC"
    cd "$OTBR_SRC"
    ./script/bootstrap
    # NAT64/DNS64 off keeps the build small and the runtime light; the bulbs
    # only ever need IPv6 inside the mesh.
    INFRA_IF_NAME="${INFRA_IF:-wlan0}" NAT64=0 DNS64=0 WEB_GUI=0 ./script/setup
    cd - >/dev/null
fi

say "Border router service options"
# Pick the backbone interface at start time rather than hardcoding it: a Pi
# that moves between Ethernet and Wi-Fi would otherwise crash-loop on
# "CreateIcmp6Socket(): No such device".
install -m 755 /dev/stdin /usr/local/bin/otbr-start <<'WRAP'
#!/bin/sh
set -eu
RADIO_URL="${OTBR_RADIO_URL:-spinel+hdlc+uart:///dev/ttyACM0}"
RADIO_DEV=$(printf '%s' "$RADIO_URL" | sed 's|^[^:]*://||; s|?.*$||')
[ -e "$RADIO_DEV" ] || { echo "otbr-start: radio $RADIO_DEV missing" >&2; exit 1; }
BACKBONE=$(ip -o route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)
[ -n "$BACKBONE" ] || { echo "otbr-start: no default route" >&2; exit 1; }
echo "otbr-start: backbone=$BACKBONE radio=$RADIO_URL"
exec /usr/sbin/otbr-agent -I wpan0 -B "$BACKBONE" "$RADIO_URL"
WRAP

mkdir -p /etc/systemd/system/otbr-agent.service.d
cat > /etc/systemd/system/otbr-agent.service.d/override.conf <<'EOF'
[Unit]
Wants=network-online.target
After=network-online.target

[Service]
ExecStart=
ExecStart=/usr/local/bin/otbr-start
Restart=on-failure
RestartSec=10
EOF

say "Node.js $NODE_MAJOR"
if ! command -v node >/dev/null || [[ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt 22 ]]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
fi
echo "   node $(node -v)"

say "matter-server"
mkdir -p "$MATTER_DIR"
cat > "$MATTER_DIR/package.json" <<'EOF'
{ "name": "kajplats-matter", "private": true,
  "dependencies": { "matter-server": "^1.5.5" } }
EOF
cd "$MATTER_DIR"
npm install --omit=dev
# npm 12 blocks native postinstall scripts by default. Skip this and the
# package installs "successfully" while the Bluetooth HCI bindings are never
# built - commissioning then fails with an unrelated-looking error.
npm install-scripts approve @stoprocent/noble @stoprocent/bluetooth-hci-socket \
    @stoprocent/bleno @serialport/bindings-cpp usb 2>/dev/null || true
npm install --omit=dev
chown -R "$MATTER_USER":"$MATTER_USER" "$MATTER_DIR"
install -d -o "$MATTER_USER" -g "$MATTER_USER" "$STORAGE"

say "matter-server service"
cat > /etc/systemd/system/matter-server.service <<EOF
[Unit]
Description=Matter Server (kajplats)
After=network-online.target bluetooth.service otbr-agent.service
Wants=network-online.target

[Service]
Type=simple
User=$MATTER_USER
WorkingDirectory=$MATTER_DIR
ExecStart=/usr/bin/node $MATTER_DIR/node_modules/matter-server/dist/esm/bin.js \\
    --storage-path $STORAGE \\
    --bluetooth-adapter 0 \\
    --listen-address 127.0.0.1 \\
    --log-level info

# noble can open an HCI socket unprivileged but the ioctls and raw HCI
# commands it issues afterwards need these; without them the adapter never
# leaves state "unknown" and BLE scanning silently never starts.
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable otbr-agent matter-server

cat <<EOF

$(say "Done")
Installed, but NOT started - the Thread dataset and Matter fabric still need
to come over from the laptop. Run this on the laptop next:

    tools/pi-migrate.sh <pi-hostname-or-ip>

It stops the laptop's services, copies the dataset and the matter-server
storage (which carries the Matter fabric, so the bulbs do not need
re-commissioning), and starts everything here.

matter-server listens on 127.0.0.1 only. Reach it from the laptop with:

    ssh -N -L 5580:localhost:5580 $MATTER_USER@<this-pi>
    uv run kajplats --matter
EOF
