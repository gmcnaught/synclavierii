#!/bin/bash
# Run the core on a MiSTer and read its screen back (the hardware test).
#
#   scripts/mister/mister_run.sh RBF [KEYS...]
#
# Installs RBF as /media/fat/_Computer/Synclavier_<date>.rbf, the floppy
# images (made from $SYNCLAVIER_RELEASE_L with tools/ned_disk.py --floppy:
# F0=03-SYSTD, F1=18-UTILS unless F0= / F1= say otherwise) in
# /media/fat/games/Synclavier, and an MGL that mounts them; loads it, waits
# WAIT seconds (default 12), types KEYS with mister_keys.py on the MiSTer
# (e.g. "text:CATALOG\r" sleep:3), takes a screenshot and copies it to
# out/mister/<TAG>.png (TAG default "run"), then prints the screen text
# (tools/screen_text.py). KEEP=0 returns to the menu core afterwards.
# STATE=1: also make a state image of ORK-LM's start (tools/state_image.py)
# and mount it in S2, with F0=03-SYSTD, F1=14-RTPO1 (as the simulator has
# them): the core starts ORK-LM.
#
# MISTER=root@192.168.20.204 by default (SSH key login).
set -euo pipefail
cd "$(dirname "$0")/../.."
RBF=${1:?usage: mister_run.sh RBF [KEYS...]}; shift
DEV=${MISTER:-root@192.168.20.204}
STATE=${STATE:-0}
if [ "$STATE" = 1 ]; then F1=${F1:-14-RTPO1}; fi
F0=${F0:-03-SYSTD}; F1=${F1:-18-UTILS}; TAG=${TAG:-run}
IMG=${SYNCLAVIER_RELEASE_L:?set SYNCLAVIER_RELEASE_L to the Release L .simg}
OUT=out/mister; mkdir -p "$OUT"
DATE=$(date +%Y%m%d)

for f in "$F0" "$F1"; do
    python3 tools/ned_disk.py "$IMG" --floppy "$f" "$OUT/$f.IMG" >/dev/null
done
S2=""
if [ "$STATE" = 1 ]; then
    [ -f "$OUT/ORK-LM.SST" ] || python3 tools/state_image.py "$IMG" "$OUT/ORK-LM.SST"
    # mounted first: the boot loader takes S2 if it is there when it starts
    S2='    <file delay="2" type="s" index="2" path="ORK-LM.SST"/>'
fi
cat > "$OUT/Synclavier-test.mgl" <<EOF
<mistergamedescription>
    <rbf>_Computer/Synclavier</rbf>
$S2
    <file delay="2" type="s" index="0" path="$F0.IMG"/>
    <file delay="1" type="s" index="1" path="$F1.IMG"/>
</mistergamedescription>
EOF

ssh "$DEV" "mkdir -p /media/fat/games/Synclavier; rm -f /media/fat/_Computer/Synclavier_*.rbf /media/fat/screenshots/Synclavier/*.png"
scp -q "$RBF" "$DEV:/media/fat/_Computer/Synclavier_$DATE.rbf"
scp -q "$OUT/$F0.IMG" "$OUT/$F1.IMG" "$DEV:/media/fat/games/Synclavier/"
if [ "$STATE" = 1 ]; then scp -q "$OUT/ORK-LM.SST" "$DEV:/media/fat/games/Synclavier/"; fi
scp -q "$OUT/Synclavier-test.mgl" "$DEV:/media/fat/"
scp -q scripts/mister/mister_keys.py "$DEV:/tmp/"
# MiSTer_cmd is a FIFO read by Main_MiSTer: never block on it
ssh "$DEV" "timeout 10 sh -c 'echo load_core /media/fat/Synclavier-test.mgl > /dev/MiSTer_cmd'; sleep ${WAIT:-12}"
if [ $# -gt 0 ]; then ssh "$DEV" "python3 /tmp/mister_keys.py $(printf '%q ' "$@")"; fi
ssh "$DEV" "sleep 1; timeout 10 sh -c 'echo screenshot > /dev/MiSTer_cmd'; sleep 2"
SHOT=$(ssh "$DEV" "ls -t /media/fat/screenshots/Synclavier/ | head -1")
scp -q "$DEV:/media/fat/screenshots/Synclavier/$SHOT" "$OUT/$TAG.png"
echo "$OUT/$TAG.png"
python3 tools/screen_text.py "$OUT/$TAG.png"
if [ "${KEEP:-1}" = 0 ]; then
    ssh "$DEV" "timeout 10 sh -c 'echo load_core /media/fat/menu.rbf > /dev/MiSTer_cmd'"
fi
