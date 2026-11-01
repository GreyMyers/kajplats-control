#!/bin/sh
# Launch otbr-agent with the backbone interface chosen at start time.
#
# The Thread border router has to be told which LAN interface to bridge onto.
# Hardcoding it in /etc/default/otbr-agent breaks the moment that interface
# changes - unplug a USB ethernet dongle and fail over to wifi, and the
# service crash-loops on "CreateIcmp6Socket(): No such device", which does not
# obviously mean "your NIC went away". Picking the interface that currently
# carries the default route survives that.
#
# Install to /usr/local/bin/otbr-start and point the unit's ExecStart at it.

set -eu

RADIO_URL="${OTBR_RADIO_URL:-spinel+hdlc+uart:///dev/ttyACM0}"
THREAD_IF="${OTBR_THREAD_IF:-wpan0}"

# The RCP's device node, e.g. /dev/ttyACM0 out of the spinel URL.
RADIO_DEV=$(printf '%s' "$RADIO_URL" | sed 's|^[^:]*://||; s|?.*$||')

if [ ! -e "$RADIO_DEV" ]; then
    echo "otbr-start: radio $RADIO_DEV is not present - is the RCP plugged in?" >&2
    exit 1
fi

BACKBONE=$(ip -o route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)

if [ -z "$BACKBONE" ]; then
    echo "otbr-start: no default route, so no backbone interface to pick" >&2
    exit 1
fi

echo "otbr-start: backbone=$BACKBONE thread=$THREAD_IF radio=$RADIO_URL"
exec /usr/bin/otbr-agent -I "$THREAD_IF" -B "$BACKBONE" "$RADIO_URL"
