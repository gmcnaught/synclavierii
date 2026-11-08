#!/usr/bin/env bash
# Build the Synclavier MiSTer core (Synclavier.qpf) into an RBF with
# Quartus Lite 17.0: locally (quartus_sh on PATH) or in CI, inside the
# raetro/quartus:17.0 Docker image (.github/workflows/build-rbf.yml).
#
# Usage: mister/build.sh [output_dir]       (default: mister/output_files)
# SYNCLAVIER_SEED=N overrides the fitter seed for this build.
#
# Prints the resource summary and the timing summary; exits non-zero when
# the compile fails or any clock domain has negative setup or hold slack.
# (Report printing is never fatal: `| head` ends pipelines early, which
# pipefail would turn into a SIGPIPE exit.)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PROJECT=Synclavier
OUTDIR="${1:-output_files}"

for q in quartus_sh /opt/intelFPGA/quartus/bin/quartus_sh /c/intelFPGA_lite/17.0/quartus/bin64/quartus_sh.exe; do
    if command -v "$q" >/dev/null 2>&1; then QSH=$(command -v "$q"); break; fi
done
[ -n "${QSH:-}" ] || { echo "ERROR: quartus_sh not found (PATH, /opt/intelFPGA, C:/intelFPGA_lite/17.0)" >&2; exit 127; }
QBIN=$(dirname "$QSH")
"$QSH" --version | head -2

if [ -n "${SYNCLAVIER_SEED:-}" ]; then
    case "$SYNCLAVIER_SEED" in ''|*[!0-9]*) echo "ERROR: SYNCLAVIER_SEED must be an integer" >&2; exit 2;; esac
    sed -i.bak "s/^set_global_assignment -name SEED .*/set_global_assignment -name SEED $SYNCLAVIER_SEED/" $PROJECT.qsf
    grep -n "name SEED" $PROJECT.qsf
fi

status=0
if ! "$QSH" --flow compile $PROJECT 2>&1 | tee build.log; then status=1; fi

echo
echo "== Resources =="
for stage in map fit; do
    rpt=output_files/$PROJECT.$stage.rpt
    [ -f "$rpt" ] || continue
    awk '/^; *Resource +; *Usage/{s=1} s{print} s&&/^\+---/{n++} s&&n>=2{exit}' "$rpt" | head -40 || true
done
fit=output_files/$PROJECT.fit.summary
[ -f "$fit" ] && cat "$fit"
grep -hE "uninferred|can't infer memory|Error \(" build.log 2>/dev/null | sort -u | head -40 || true

if [ -f output_files/$PROJECT.sta.rpt ]; then
    "$QBIN/quartus_sta" -t sta_paths.tcl >/dev/null 2>&1 || echo "(worst-path report failed)"
    if [ -f output_files/worst_paths.txt ]; then head -80 output_files/worst_paths.txt || true; fi
fi

echo
echo "== Timing =="
sta=output_files/$PROJECT.sta.summary
if [ -f "$sta" ]; then
    cat "$sta"
    # "Slack : -1.234" lines; any negative slack fails the build
    if grep -E "^Slack *: *-" "$sta" >/dev/null; then
        echo "TIMING FAILED: negative slack above"
        status=1
    fi
else
    echo "no timing summary"
    status=1
fi

rbf=output_files/$PROJECT.rbf
if [ -f "$rbf" ]; then
    mkdir -p "$OUTDIR"
    if [ "$OUTDIR" != output_files ]; then cp "$rbf" "$OUTDIR/Synclavier_$(date -u +%Y%m%d).rbf"; fi
    ls -l "$rbf"
else
    echo "no RBF produced"
    status=1
fi
exit $status
