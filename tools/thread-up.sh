#!/bin/sh
# Form a Thread network on the running otbr-agent and print its dataset.
#
# Idempotent: if the border router is already attached to a network, this
# reports it and prints the existing dataset rather than forming a second one.
# Forming a new network when bulbs are already commissioned onto the old one
# would orphan them.
#
# Run as root:  sudo sh tools/thread-up.sh

set -eu

run() { ot-ctl "$@" 2>&1 | grep -v '^Done$' || true; }

if ! ot-ctl state >/dev/null 2>&1; then
    echo "error: cannot reach otbr-agent. Is the service running, and are you root?" >&2
    exit 1
fi

STATE=$(ot-ctl state 2>/dev/null | head -1 | tr -d '\r')

case "$STATE" in
    leader|router|child)
        echo "Thread is already up (state: $STATE) - reusing the existing network."
        ;;
    *)
        echo "Current state: ${STATE:-unknown}. Forming a new Thread network..."
        run dataset init new
        run dataset commit active
        run ifconfig up
        run thread start

        printf 'waiting for attach'
        i=0
        while [ "$i" -lt 30 ]; do
            STATE=$(ot-ctl state 2>/dev/null | head -1 | tr -d '\r')
            case "$STATE" in
                leader|router|child) break ;;
            esac
            printf '.'
            sleep 1
            i=$((i + 1))
        done
        printf '\n'

        case "$STATE" in
            leader|router|child) echo "attached as: $STATE" ;;
            *)
                echo "error: did not attach (state: ${STATE:-unknown})." >&2
                echo "Check: journalctl -u otbr-agent -n 40" >&2
                exit 1
                ;;
        esac
        ;;
esac

echo
echo "network name : $(ot-ctl networkname 2>/dev/null | head -1 | tr -d '\r')"
echo "pan id       : $(ot-ctl panid      2>/dev/null | head -1 | tr -d '\r')"
echo "channel      : $(ot-ctl channel    2>/dev/null | head -1 | tr -d '\r')"
echo
echo "Thread dataset (paste this into the app's \"Add bulb...\" dialog):"
echo
ot-ctl dataset active -x 2>/dev/null | head -1 | tr -d '\r'
echo
