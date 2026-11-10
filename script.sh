#!/usr/bin/env bash
set -euo pipefail

DL="${HOME}/Downloads"
T50="${T50:-$DL/t50-auto-sb3.img}"
CURRENT="${1:-${CURRENT:-}}"

if [[ ! -f "$T50" ]]; then
  echo "ERROR: missing reference image: $T50" >&2
  exit 1
fi

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
  echo "Put boot*.img in ~/Downloads or run: ./script.sh /path/to/boot.img" >&2
  exit 1
fi

base="$(basename "$CURRENT" .img)"
OUT="${2:-$DL/${base}-t50shell.img}"
REPORT="${OUT%.img}.json"

echo "t50    : $T50"
echo "current: $CURRENT"
echo "output : $OUT"
echo

python3 - "$T50" "$CURRENT" "$OUT" "$REPORT" <<'PY'
import gzip
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

PAGE = 4096
FD_SIZE = 0x300000
V3_HEADER_SIZE = 1580

def align(v):
    return (v + PAGE - 1) // PAGE * PAGE

def sha256(b):
    return hashlib.sha256(b).hexdigest()

def unpack(path):
    path = Path(path)
    data = path.read_bytes()
    if len(data) < PAGE or data[:8] != b"ANDROID!":
        raise SystemExit(f"{path}: not an Android boot image")

    version = struct.unpack_from("<I", data, 40)[0]
    if version == 3:
        kernel_size = struct.unpack_from("<I", data, 8)[0]
        ramdisk_size = struct.unpack_from("<I", data, 12)[0]
        header_size = struct.unpack_from("<I", data, 20)[0]
        if header_size != V3_HEADER_SIZE:
            raise SystemExit(f"{path}: unexpected v3 header_size {header_size}")
        page = PAGE
    else:
        (kernel_size, _, ramdisk_size, _, second_size, _, _, page,
         version, _) = struct.unpack_from("<10I", data, 8)
        if page != PAGE or second_size:
            raise SystemExit(f"{path}: unsupported v{version}/page{page}/second{second_size}")

    kernel = data[page:page + kernel_size]
    if len(kernel) != kernel_size:
        raise SystemExit(f"{path}: truncated kernel field")

    u = zlib.decompressobj(16 + zlib.MAX_WBITS)
    combined = u.decompress(kernel)
    if not u.eof:
        raise SystemExit(f"{path}: gzip stream incomplete")
    dtb = u.unused_data
    if len(dtb) < 8 or dtb[:4] != b"\xd0\x0d\xfe\xed":
        raise SystemExit(f"{path}: no appended FDT")
    dtb_size = struct.unpack_from(">I", dtb, 4)[0]
    if dtb_size != len(dtb):
        raise SystemExit(f"{path}: FDT size mismatch {dtb_size:#x} != {len(dtb):#x}")

    fvh = combined.find(b"_FVH")
    if fvh < 0x28:
        raise SystemExit(f"{path}: UEFI FV header not found")
    fd_start = fvh - 0x28
    payload_start = fd_start + FD_SIZE
    if payload_start > len(combined):
        raise SystemExit(f"{path}: UEFI FD exceeds image")

    payload = combined[payload_start:]
    if len(payload) < 512 or payload[510:512] != b"\x55\xaa":
        raise SystemExit(f"{path}: FAT payload not found at {payload_start:#x}")

    start = page + align(kernel_size)
    ramdisk = data[start:start + ramdisk_size]
    if len(ramdisk) != ramdisk_size:
        raise SystemExit(f"{path}: truncated ramdisk")

    return {
        "data": data,
        "version": version,
        "kernel_size": kernel_size,
        "combined": combined,
        "dtb": dtb,
        "fd_start": fd_start,
        "payload_start": payload_start,
        "payload": payload,
        "ramdisk_size": ramdisk_size,
        "ramdisk": ramdisk,
    }

t50_path, current_path, out_path, report_path = map(Path, sys.argv[1:5])
t50 = unpack(t50_path)
cur = unpack(current_path)

if t50["version"] != 3:
    raise SystemExit(f"{t50_path}: expected Android header v3")
if t50["ramdisk_size"] != 1 or t50["ramdisk"] != b"\0":
    raise SystemExit(f"{t50_path}: expected one-byte zero ramdisk")

text_offset, image_size = struct.unpack_from("<QQ", t50["combined"], 8)
if t50["combined"][56:60] != b"ARM\x64":
    raise SystemExit(f"{t50_path}: ARM64 magic missing")
if image_size != t50["payload_start"]:
    raise SystemExit(
        f"{t50_path}: not t50 loader contract: "
        f"image_size={image_size:#x}, BootShim+FD={t50['payload_start']:#x}"
    )

prefix = t50["combined"][:t50["payload_start"]]
new_combined = prefix + cur["payload"]
new_kernel = gzip.compress(new_combined, compresslevel=9, mtime=0) + t50["dtb"]

header = bytearray(t50["data"][:PAGE])
struct.pack_into("<I", header, 8, len(new_kernel))

out = bytes(header)
out += new_kernel
out += b"\0" * (align(len(new_kernel)) - len(new_kernel))
out += t50["ramdisk"]
out += b"\0" * (align(len(t50["ramdisk"])) - len(t50["ramdisk"]))

u = zlib.decompressobj(16 + zlib.MAX_WBITS)
round_combined = u.decompress(new_kernel)
if not u.eof or u.unused_data != t50["dtb"]:
    raise SystemExit("internal error: DTB changed")
if round_combined[:len(prefix)] != prefix:
    raise SystemExit("internal error: t50 loader shell changed")
if round_combined[len(prefix):] != cur["payload"]:
    raise SystemExit("internal error: current payload changed")

out_path.write_bytes(out)

report = {
    "mode": "t50-loader-shell-current-payload",
    "t50_sha256": sha256(t50["data"]),
    "current_sha256": sha256(cur["data"]),
    "output_sha256": sha256(out),
    "outer_header_version": 3,
    "t50_shim_bytes": t50["fd_start"],
    "current_shim_bytes": cur["fd_start"],
    "uefi_fd_bytes": FD_SIZE,
    "t50_prefix_bytes": len(prefix),
    "current_payload_bytes": len(cur["payload"]),
    "inner_arm64_text_offset": text_offset,
    "inner_arm64_image_size": image_size,
    "output_bytes": len(out),
}
report_path.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
PY

echo
echo "DONE"
echo "image : $OUT"
echo "report: $REPORT"
echo
echo "Manual device test only:"
printf 'fastboot boot %q\n' "$OUT"
