#!/usr/bin/env bash
# List connected Espressif boards by their stable /dev/serial/by-id path, and
# flag whichever one is currently acting as the Thread border router.
#
# ttyACM numbering is assigned in plug order, so it changes between reboots
# and between replugs. Flashing "ttyACM1" from memory is how you overwrite
# the border router's RCP firmware and take the lights down. The by-id path
# contains the board's MAC and never moves.
#
#   tools/esp-boards.sh
#   idf.py -p "$(tools/esp-boards.sh --free)" flash

set -uo pipefail

BYID=/dev/serial/by-id
FREE_ONLY=0
[[ "${1:-}" == "--free" ]] && FREE_ONLY=1

# Which board is the RCP. This must be decided by identity, not by device
# path: /dev/ttyACM* numbering is assigned in plug order, so comparing paths
# labels whichever board happens to be ttyACM0 as the border router - which
# is exactly backwards when the RCP is unplugged and a different board takes
# its number.
RCP_PIN="$(dirname "$0")/rcp-board"
RCP_ID=""
[[ -r "$RCP_PIN" ]] && RCP_ID=$(grep -v '^#' "$RCP_PIN" | tr -d '[:space:]' | head -1)

BR_PORT=""
if [[ -r /etc/default/otbr-agent ]]; then
    BR_PORT=$(sed -n 's|.*spinel+hdlc+uart://\([^ "?]*\).*|\1|p' /etc/default/otbr-agent | head -1)
fi
BR_ACTIVE=0
systemctl is-active --quiet otbr-agent 2>/dev/null && BR_ACTIVE=1

shopt -s nullglob
LINKS=("$BYID"/*Espressif* "$BYID"/*CP210* "$BYID"/*CH340*)
shopt -u nullglob

if [[ -n "$BR_PORT" && "$BR_PORT" == /dev/ttyACM* ]]; then
    echo "warning: /etc/default/otbr-agent points at '$BR_PORT', a plug-order" >&2
    echo "         path. With two boards attached otbr-agent can bind the wrong" >&2
    echo "         one. Point it at a /dev/serial/by-id/... path instead." >&2
    echo >&2
fi

if [[ ${#LINKS[@]} -eq 0 ]]; then
    if (( FREE_ONLY )); then
        echo "no-board-found" >&2
        exit 1
    fi
    echo "No Espressif boards found."
    echo
    echo "Plug one in and re-run. If it still does not appear:"
    echo "  - try a different USB cable (charge-only cables are common)"
    echo "  - check 'lsusb' for 303a:1001"
    echo "  - check 'journalctl -k -n 20' for enumeration errors"
    exit 1
fi

FREE_PATH=""
for link in "${LINKS[@]}"; do
    real=$(readlink -f "$link")
    name=$(basename "$link")
    tag="free"
    if [[ -n "$RCP_ID" && "$name" == *"$RCP_ID"* ]]; then
        if (( BR_ACTIVE )); then
            tag="RCP - BORDER ROUTER, do not flash"
        else
            tag="RCP (border router service stopped)"
        fi
    elif [[ -z "$RCP_ID" ]]; then
        tag="free (no tools/rcp-board pin - identity unknown)"
    fi
    [[ "$tag" == "free" && -z "$FREE_PATH" ]] && FREE_PATH="$link"

    if (( ! FREE_ONLY )); then
        printf '%s\n   -> %s   [%s]\n' "$link" "$real" "$tag"
    fi
done

if (( FREE_ONLY )); then
    if [[ -z "$FREE_PATH" ]]; then
        echo "no-free-board" >&2
        exit 1
    fi
    echo "$FREE_PATH"
fi
