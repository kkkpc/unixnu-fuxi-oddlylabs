#!/usr/bin/env python3
"""Rewrap a fuxi UniXNU Android boot-v0 image in a boot-v3 outer envelope.

The kernel field is copied byte-for-byte. Only the outer Android boot header and
one-byte ramdisk placeholder change. This reproduces the outer v3 envelope used
by the owner-verified t50-auto-sb3.img, but deliberately does NOT reproduce
t50's inner BootShim/UEFI/image_size contract. Use make-t50-shell-candidate.py
for the exact-loader-shell fallback.

Usage:
  rewrap-fuxi-boot-v3.py INPUT_V0 OUTPUT_V3 [--report boot.json]
"""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

PAGE = 4096
V3_HEADER_SIZE = 1580


def align(value):
    return (value + PAGE - 1) // PAGE * PAGE


def sha256(blob):
    return hashlib.sha256(blob).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("input", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--report", type=Path)
args = parser.parse_args()

src = args.input.read_bytes()
if len(src) < PAGE or src[:8] != b"ANDROID!":
    raise SystemExit("input is not an Android boot image")

(kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
 second_size, second_addr, tags_addr, page_size,
 header_version, os_version) = struct.unpack_from("<10I", src, 8)

if header_version != 0 or page_size != PAGE or second_size != 0:
    raise SystemExit(
        f"expected fuxi source boot v0/page4096/no-second, got "
        f"v{header_version}/page{page_size}/second{second_size}"
    )

kernel = src[PAGE:PAGE + kernel_size]
if len(kernel) != kernel_size:
    raise SystemExit("source kernel field is truncated")

unpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
unpacker.decompress(kernel)
if not unpacker.eof or unpacker.unused_data[:4] != b"\xd0\x0d\xfe\xed":
    raise SystemExit("source kernel field is not gzip(UniXNU image)+FDT")

header = bytearray(PAGE)
header[:8] = b"ANDROID!"
struct.pack_into("<I", header, 8, kernel_size)
struct.pack_into("<I", header, 12, 1)
struct.pack_into("<I", header, 16, 0)
struct.pack_into("<I", header, 20, V3_HEADER_SIZE)
struct.pack_into("<I", header, 40, 3)

out = bytes(header)
out += kernel
out += b"\0" * (align(kernel_size) - kernel_size)
out += b"\0"
out += b"\0" * (PAGE - 1)

if out[:8] != b"ANDROID!" or struct.unpack_from("<I", out, 40)[0] != 3:
    raise SystemExit("internal v3 header check failed")
if struct.unpack_from("<I", out, 20)[0] != V3_HEADER_SIZE:
    raise SystemExit("internal v3 header_size check failed")
if out[PAGE:PAGE + kernel_size] != kernel:
    raise SystemExit("kernel field changed while rewrapping")

args.output.write_bytes(out)

if args.report:
    report = json.loads(args.report.read_text())
    if report.get("image_sha256") != sha256(src) or report.get("image_bytes") != len(src):
        raise SystemExit("source boot image does not match boot.json")
    report["source_header_version"] = report.get("header_version")
    report["source_image_sha256"] = report.get("image_sha256")
    report["source_image_bytes"] = report.get("image_bytes")
    report["header_version"] = 3
    report["ramdisk_bytes"] = 1
    report["image_sha256"] = sha256(out)
    report["image_bytes"] = len(out)
    report["wrapper"] = "android-v3-envelope-only"
    report["wrapper_kernel_preserved"] = True
    report["t50_inner_contract_preserved"] = False
    args.report.write_text(json.dumps(report, indent=2) + "\n")

print(json.dumps({
    "source_header_version": 0,
    "header_version": 3,
    "kernel_bytes": kernel_size,
    "source_bytes": len(src),
    "image_bytes": len(out),
    "kernel_sha256": sha256(kernel),
    "image_sha256": sha256(out),
}, indent=2))
