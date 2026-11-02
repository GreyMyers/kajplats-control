#!/usr/bin/env bash
# Snapshot of how the esp-matter install is progressing.
#
# install.sh prints very little while it works, and most of the time is spent
# inside nested pip and ninja invocations whose output never reaches the
# terminal. So rather than watching for log lines, this samples the things
# that actually move: package counts in the two virtualenvs, the size on
# disk, and the mtime of the most recently touched file.
#
#   tools/matter-install-status.sh            one snapshot
#   watch -n 15 tools/matter-install-status.sh   live
#
# "Last activity" is the number to watch. If it keeps resetting to a few
# seconds, work is happening even when nothing is printed. If it climbs past
# several minutes while a pip process is alive, the download has likely
# stalled on the network rather than crashed.

ESP_MATTER="${ESP_MATTER:-$HOME/esp/esp-matter}"
CHIP="$ESP_MATTER/connectedhomeip/connectedhomeip"
ENV="$CHIP/.environment"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }

if [[ ! -d "$ESP_MATTER" ]]; then
    echo "esp-matter not found at $ESP_MATTER"
    exit 1
fi

bold "processes"
FOUND=0
while read -r pid etime cmd; do
    [[ -z "$pid" ]] && continue
    printf '  %-8s running %-10s %s\n' "$pid" "$etime" "$(echo "$cmd" | cut -c1-58)"
    FOUND=1
done < <(ps -eo pid,etime,args --no-headers 2>/dev/null \
         | grep -E 'ninja|install\.sh|bootstrap|[p]ip ' \
         | grep -v 'grep\|claude\|snapshot-bash\|matter-install-status' \
         | awk '{pid=$1; et=$2; $1=""; $2=""; print pid, et, $0}')
(( FOUND )) || echo "  none — install is finished or stopped"

# Absolute counts do not answer "is it stuck?" - you have to remember the
# previous value. Cache each sample and show the delta instead.
STATE="${TMPDIR:-/tmp}/.matter-install-status.$UID"
PREV=""
[[ -f "$STATE" ]] && PREV=$(cat "$STATE")
NOW=""

bold "virtualenv packages (these climb as it works)"
for name in pigweed-venv gn_out/python-venv; do
    d="$ENV/$name/lib/python3.14/site-packages"
    [[ -d "$d" ]] || continue
    short="${name%%/*}"
    count=$(ls "$d" 2>/dev/null | wc -l)
    delta=""
    if [[ -n "$PREV" ]]; then
        was=$(echo "$PREV" | awk -v k="$short" '$1==k {print $2}')
        if [[ -n "$was" ]]; then
            diff=$(( count - was ))
            if   (( diff > 0 )); then delta="  (+$diff since last check)"
            elif (( diff == 0 )); then delta="  (unchanged)"
            fi
        fi
    fi
    printf '  %-22s %-5s%s\n' "$short" "$count" "$delta"
    NOW+="$short $count"$'\n'
done
printf '%s' "$NOW" > "$STATE"

bold "size and space"
printf '  esp-matter on disk     %s\n' "$(du -sh "$ESP_MATTER" 2>/dev/null | cut -f1)"
printf '  free on /              %s\n' "$(df -h / | awk 'NR==2 {print $4}')"

# The decisive liveness signal. Package counts only move during pip phases,
# so they sit still for long stretches while compilation happens - which
# reads as "stuck" when it is not. CPU time cannot sit still on a process
# that is doing anything at all.
bold "cpu burned since last check"
CPUSTATE="${TMPDIR:-/tmp}/.matter-install-cpu.$UID"
TICKS=0
for p in $(pgrep -f 'install\.sh|ninja -C.*esp-matter|esp-matter.*python' 2>/dev/null); do
    [[ -r /proc/$p/stat ]] && TICKS=$(( TICKS + $(awk '{print $14+$15}' /proc/$p/stat 2>/dev/null || echo 0) ))
done
NOW_S=$(date +%s)
if [[ -f "$CPUSTATE" ]]; then
    read -r PT PS_ < "$CPUSTATE"
    DT=$(( NOW_S - PS_ ))
    DC=$(( TICKS - PT ))
    if (( DT <= 0 )); then
        echo "  checked again too soon to measure - wait a few seconds"
    else
        if (( DC > 0 )); then
            printf '  %s cpu-seconds over %ss  -> alive\n' \
                   "$(awk -v d=$DC 'BEGIN{printf "%.1f", d/100}')" "$DT"
        else
            printf '  no cpu used over %ss  -> stalled or finished\n' "$DT"
        fi
    fi
else
    echo "  (first run - baseline recorded)"
fi
echo "$TICKS $NOW_S" > "$CPUSTATE"

bold "last activity"
NEWEST=$(find "$ENV" -type f -newermt '-6 hours' -printf '%T@ %p\n' 2>/dev/null \
         | sort -rn | head -1)
if [[ -n "$NEWEST" ]]; then
    TS=${NEWEST%% *}
    AGE=$(( $(date +%s) - ${TS%.*} ))
    printf '  %s ago: %s\n' "$(printf '%dm%02ds' $((AGE/60)) $((AGE%60)))" \
           "$(basename "${NEWEST#* }")"
else
    echo "  nothing touched recently"
fi

bold "done?"
if [[ -f "$ESP_MATTER/export.sh" ]] && \
   [[ -d "$ENV/cipd/packages/zap" ]] && \
   [[ -f "$ENV/pigweed-venv/bin/python" ]] && \
   "$ENV/pigweed-venv/bin/python" -c "import chip" 2>/dev/null; then
    echo "  looks complete — try: source $ESP_MATTER/export.sh"
else
    echo "  not yet: the chip python module is not importable"
fi
