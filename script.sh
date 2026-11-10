#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DL="${HOME}/Downloads"
T50="${T50:-$DL/t50-auto-sb3.img}"
CURRENT="${1:-${CURRENT:-}}"

if [[ ! -f "$T50" ]]; then
  echo "ERROR: missing reference image: $T50" >&2
  exit 1
fi

# No argument: pick the newest boot*.img in ~/Downloads, excluding t50-shell outputs.
if [[ -z "$CURRENT" ]]; then
  newest=0
  for f in "$DL"/boot*.img; do
    [[ -f "$f" ]] || continue
    [[ "$f" == "$T50" || "$f" == *-t50shell.img ]] && continue
    mtime="$(stat -f '%m' "$f" 2>/dev/null || stat -c '%Y' "$f")"
    if (( mtime > newest )); then
      newest="$mtime"
      CURRENT="$f"
    fi
  done
fi

if [[ -z "$CURRENT" || ! -f "$CURRENT" ]]; then
  echo "ERROR: no current boot image found." >&2
  echo "Put boot*.img in ~/Downloads or run: bash script.sh /path/to/boot.img" >&2
  exit 1
fi

base="$(basename "$CURRENT" .img)"
OUT="${2:-$DL/${base}-t50shell.img}"
REPORT="${OUT%.img}.json"

echo "t50    : $T50"
echo "current: $CURRENT"
echo "output : $OUT"
echo

python3 "$ROOT/scripts/make-t50-shell-candidate.py" \
  "$T50" \
  "$CURRENT" \
  "$OUT" \
  --report "$REPORT"

echo
echo "DONE"
echo "image : $OUT"
echo "report: $REPORT"
echo
echo "Manual device test only:"
printf 'fastboot boot %q\n' "$OUT"
