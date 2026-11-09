#!/usr/bin/env python3
"""Check the fuxi GPU userspace addon and payload handoff contract."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def fail(message):
    raise SystemExit("FAIL: " + message)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_contract():
    board = (ROOT / "board.toml").read_text()
    workflow = (ROOT / ".github/workflows/build.yml").read_text()
    for needle in ("sheng-gpu-addon=1",):
        if needle not in board:
            fail("board no longer enables the GPU addon loader: " + needle)
    for needle in ("Build Adreno Metal userspace addon", "prepare-fuxi-metal-userspace.py",
                   "make-fuxi-gpu-addon.py", "--gpu-addon", "--owner-trust-cache"):
        if needle not in workflow:
            fail("workflow GPU payload contract is missing: " + needle)
    start = workflow.find("- name: Build payload")
    end = workflow.find("\n      - name:", start + 1)
    block = workflow[start:end if end >= 0 else None]
    if "--trust-cache" in block:
        fail("Build payload still passes the original trust cache instead of the owner bundle")
    print("PASS: source workflow carries the Adreno Metal addon and owner-trust payload contract")

def addon_contract(path):
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"NGPUADD2":
        fail("GPU addon header is not NGPUADD2")
    count, reserved, total = struct.unpack_from("<IIQ", data, 8)
    if reserved != 0 or count < 4 or total != len(data):
        fail(f"GPU addon header is inconsistent: count={count} reserved={reserved} total={total} bytes={len(data)}")
    print(f"PASS: GPU addon NGPUADD2, {count} files, {len(data)} bytes")

def trust_contract(path):
    data = path.read_bytes()
    if len(data) < 16:
        fail("owner trust bundle is too small")
    count = struct.unpack_from("<I", data)[0]
    if count != 3:
        fail(f"owner trust bundle must contain owner + two original modules; got {count}")
    offsets = struct.unpack_from("<3I", data, 4)
    if offsets[0] < 16 or tuple(sorted(offsets)) != offsets or offsets[-1] >= len(data):
        fail("owner trust bundle offsets are invalid")
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        if end - start < 24 or struct.unpack_from("<I", data, start)[0] != 2:
            fail(f"trust module {i} is not a complete v2 module")
        entries = struct.unpack_from("<I", data, start + 20)[0]
        if end - start != 24 + entries * 24:
            fail(f"trust module {i} length does not match its entry count")
    print(f"PASS: owner trust bundle has one owner module plus two original v2 modules ({len(data)} bytes)")

def report_contract(path, addon, owner):
    report = json.loads(path.read_text())
    if report.get("gpu_addon_sha256") != sha(addon):
        fail("payload.json GPU addon hash does not match the built addon")
    if report.get("trust_cache_sha256") != sha(owner):
        fail("payload.json trust hash does not match the owner trust bundle")
    print("PASS: payload.json records the exact GPU addon and owner trust bundle")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon", type=Path)
    parser.add_argument("--owner-trust", type=Path)
    parser.add_argument("--payload-report", type=Path)
    args = parser.parse_args()
    source_contract()
    if bool(args.addon) != bool(args.owner_trust):
        fail("--addon and --owner-trust must be passed together")
    if args.addon:
        addon_contract(args.addon)
        trust_contract(args.owner_trust)
    if args.payload_report:
        if not args.addon:
            fail("--payload-report requires --addon and --owner-trust")
        report_contract(args.payload_report, args.addon, args.owner_trust)

if __name__ == "__main__":
    main()
