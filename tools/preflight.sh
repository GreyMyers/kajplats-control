#!/usr/bin/env bash
# Host preflight for running a Thread border router + Matter server.
#
# Checks everything the stack needs and fixes what it safely can. Re-runnable:
# anything already correct is reported and skipped. Pass --fix to apply the
# two system changes (IPv6 forwarding, avahi); without it, nothing is changed.

set -uo pipefail

ok()    { printf '  \033[32mok\033[0m    %s\n' "$1"; }
warn()  { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }
bad()   { printf '  \033[31mmiss\033[0m  %s\n' "$1"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

FIX=0
[[ "${1:-}" == "--fix" ]] && FIX=1

head_ "RCP radio"
RCP_PORT=""
for dev in /dev/ttyACM* /dev/ttyUSB*; do
    [[ -e "$dev" ]] || continue
    RCP_PORT="$dev"
    if [[ -r "$dev" && -w "$dev" ]]; then
        ok "$dev present and writable"
    else
        bad "$dev present but not writable - add yourself to the 'uucp' group"
    fi
    break
done
[[ -z "$RCP_PORT" ]] && bad "no serial device - plug in the ESP32-C6 (enumerates as /dev/ttyACM0)"

head_ "IPv6 forwarding (otbr routes between Thread and your LAN)"
if [[ "$(sysctl -n net.ipv6.conf.all.forwarding)" == "1" ]]; then
    ok "enabled"
elif (( FIX )); then
    echo 'net.ipv6.conf.all.forwarding=1' | sudo tee /etc/sysctl.d/99-thread.conf >/dev/null
    sudo sysctl -q -w net.ipv6.conf.all.forwarding=1 \
        && ok "enabled, persisted to /etc/sysctl.d/99-thread.conf"
else
    bad "disabled - rerun with --fix, or: sudo sysctl -w net.ipv6.conf.all.forwarding=1"
fi

head_ "mDNS (Matter discovers everything over it)"
if systemctl is-active --quiet avahi-daemon; then
    ok "avahi-daemon running"
elif (( FIX )); then
    sudo systemctl enable --now avahi-daemon && ok "avahi-daemon started and enabled"
else
    bad "avahi-daemon not running - rerun with --fix, or: sudo systemctl enable --now avahi-daemon"
fi

head_ "Bluetooth (needed only while commissioning)"
if systemctl is-active --quiet bluetooth; then
    ok "bluetooth service running"
else
    bad "bluetooth service stopped - sudo systemctl start bluetooth"
fi
if rfkill list bluetooth 2>/dev/null | grep -q "Soft blocked: yes"; then
    bad "adapter is soft-blocked - sudo rfkill unblock bluetooth"
else
    ok "adapter not blocked"
fi

head_ "Border router"
if command -v otbr-agent >/dev/null; then
    ok "otbr-agent installed"
else
    bad "otbr-agent missing - yay -S ot-br-posix-git"
fi

head_ "Matter server"
if command -v node >/dev/null; then
    NODE_MAJOR=$(node --version | sed 's/^v\([0-9]*\).*/\1/')
    if (( NODE_MAJOR >= 22 )); then
        ok "node $(node --version)"
    else
        bad "node $(node --version) is too old; 22.13+ required"
    fi
else
    bad "node not installed"
fi

head_ "Backbone interface"
# The interface otbr-agent bridges Thread onto. Pick the one carrying the
# default route, then warn about VPN tunnels, which cannot carry the
# link-local multicast and mDNS that Thread and Matter depend on.
BACKBONE=$(ip -o route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)
if [[ -n "$BACKBONE" ]]; then
    ok "default route leaves via '$BACKBONE'  ->  use: otbr-agent -B $BACKBONE"
else
    bad "no default route found"
fi
while read -r iface _; do
    if [[ -n "$iface" && "$iface" =~ ^(proton|tun|tap|wg|nordlynx|ipsec) ]]; then
        warn "'$iface' looks like a VPN tunnel."
        warn "  Thread and Matter need link-local IPv6 multicast and mDNS on the"
        warn "  real LAN, and a VPN often swallows both. If commissioning stalls,"
        warn "  disconnect it and retry."
    fi
done < <(ip -br link | awk '$2=="UP"||$2=="UNKNOWN" {print $1}' | cut -d@ -f1)

printf '\n'
