#!/usr/bin/env python3
"""Build a fuxi test image with the device-proven t50 loader shell and a current payload.

This tool is intentionally local-only: it never invokes fastboot, flashes, or reboots.
It preserves the t50 Android-v3 header shape, BootShim, 3 MiB UEFI FD and DTB, and
replaces only the appended FAT payload taken from CURRENT.

usage:
  make-t50-shell-candidate.py T50 CURRENT OUTPUT [--report FILE]
"""
import argparse
import gzip
import hashlib
import json
import struct
import zlib
from pathlib import Path

PAGE = 4096
FD_SIZE = 0x300000
V3_HEADER_SIZE = 1580


def align(value: int) -> int:
    return (value + PAGE - 1) // PAGE * PAGE


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def unpack(path: Path) -> dict:
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

    unpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
    combined = unpacker.decompress(kernel)
    if not unpacker.eof:
        raise SystemExit(f"{path}: gzip stream is incomplete")
    dtb = unpacker.unused_data
    if len(dtb) < 8 or dtb[:4] != b"\xd0\x0d\xfe\xed":
        raise SystemExit(f"{path}: gzip stream is not followed by an FDT")
    dtb_size = struct.unpack_from(">I", dtb, 4)[0]
    if dtb_size != len(dtb):
        raise SystemExit(f"{path}: appended FDT size {dtb_size:#x} != {len(dtb):#x}")

    fvh = combined.find(b"_FVH")
    if fvh < 0x28:
        raise SystemExit(f"{path}: UEFI FV header not found")
    fd_start = fvh - 0x28
    payload_start = fd_start + FD_SIZE
    if payload_start > len(combined):
        raise SystemExit(f"{path}: 3 MiB UEFI FD extends beyond decompressed image")
    payload = combined[payload_start:]
    if len(payload) < 512 or payload[510:512] != b"\x55\xaa":
        raise SystemExit(f"{path}: appended FAT payload not found at {payload_start:#x}")

    start = page + align(kernel_size)
    ramdisk = data[start:start + ramdisk_size]
    if len(ramdisk) != ramdisk_size:
        raise SystemExit(f"{path}: truncated ramdisk field")

    return {
        "data": data,
        "version": version,
        "page": page,
        "kernel_size": kernel_size,
        "kernel": kernel,
        "combined": combined,
        "dtb": dtb,
        "fd_start": fd_start,
        "payload_start": payload_start,
        "payload": payload,
        "ramdisk_size": ramdisk_size,
        "ramdisk": ramdisk,
    }


parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("t50", type=Path)
parser.add_argument("current", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--report", type=Path)
args = parser.parse_args()

t50 = unpack(args.t50)
current = unpack(args.current)

if t50["version"] != 3:
    raise SystemExit(f"{args.t50}: expected device-proven Android header v3, got v{t50['version']}")
if t50["ramdisk_size"] != 1 or t50["ramdisk"] != b"\0":
    raise SystemExit(f"{args.t50}: expected the proven one-byte zero ramdisk placeholder")

t50_text_offset, t50_image_size = struct.unpack_from("<QQ", t50["combined"], 8)
if t50["combined"][56:60] != b"ARM\x64":
    raise SystemExit(f"{args.t50}: ARM64 image header magic is missing")
if t50_image_size != t50["payload_start"]:
    raise SystemExit(
        f"{args.t50}: reference is not the t50 loader contract: "
        f"ARM64 image_size={t50_image_size:#x}, BootShim+FD={t50['payload_start']:#x}"
    )

# Preserve the exact device-proven loader shell. Only the FAT payload changes.
prefix = t50["combined"][:t50["payload_start"]]
new_combined = prefix + current["payload"]
new_kernel = gzip.compress(new_combined, compresslevel=9, mtime=0) + t50["dtb"]

# Preserve the t50 outer header page byte-for-byte except for kernel_size,
# which must describe the recompressed kernel field.
header = bytearray(t50["data"][:PAGE])
struct.pack_into("<I", header, 8, len(new_kernel))
out = bytes(header)
out += new_kernel
out += b"\0" * (align(len(new_kernel)) - len(new_kernel))
out += t50["ramdisk"]
out += b"\0" * (align(len(t50["ramdisk"])) - len(t50["ramdisk"]))

# Strong invariants: no accidental loader-shell, DTB or payload mutation.
round_unpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
round_combined = round_unpacker.decompress(new_kernel)
if not round_unpacker.eof or round_unpacker.unused_data != t50["dtb"]:
    raise SystemExit("internal error: t50 DTB changed")
if round_combined[:len(prefix)] != prefix:
    raise SystemExit("internal error: t50 BootShim+UEFI prefix changed")
if round_combined[len(prefix):] != current["payload"]:
    raise SystemExit("internal error: current FAT payload changed")
if bytes(header[12:]) != t50["data"][12:PAGE]:
    raise SystemExit("internal error: t50 outer header changed outside kernel_size")

args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_bytes(out)

report = {
    "mode": "t50-loader-shell-current-payload",
    "t50_sha256": sha256(t50["data"]),
    "current_sha256": sha256(current["data"]),
    "output_sha256": sha256(out),
    "outer_header_version": 3,
    "outer_header_preserved_except_kernel_size": True,
    "t50_shim_bytes": t50["fd_start"],
    "current_shim_bytes": current["fd_start"],
    "uefi_fd_bytes": FD_SIZE,
    "t50_prefix_bytes": len(prefix),
    "t50_prefix_sha256": sha256(prefix),
    "current_payload_bytes": len(current["payload"]),
    "current_payload_sha256": sha256(current["payload"]),
    "t50_dtb_bytes": len(t50["dtb"]),
    "t50_dtb_sha256": sha256(t50["dtb"]),
    "inner_arm64_text_offset": t50_text_offset,
    "inner_arm64_image_size": t50_image_size,
    "output_bytes": len(out),
}
if args.report:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")

print(json.dumps(report, indent=2))
