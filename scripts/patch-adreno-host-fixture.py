#!/usr/bin/env python3
"""Apply the small host-only XNU memory double needed by the pinned Adreno740 tests."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--tree", type=Path, required=True, help="resolved UniXNU target tree")
args = parser.parse_args()
root = args.tree.resolve()
fixture = root / "drivers/Adreno740/tests/XnuMemoryFixture.h"
needle = "inline void *IOMallocZero(size_t bytes) {return std::calloc(1,bytes);}\n"
replacement = needle + "inline void IOFree(void *ptr,size_t) {std::free(ptr);}\n"

if not fixture.is_file():
    raise SystemExit(f"Adreno740 host fixture missing: {fixture}")
text = fixture.read_text()
if "inline void IOFree(void *ptr,size_t)" in text:
    print("PASS: Adreno740 host fixture already provides IOFree")
elif needle in text:
    fixture.write_text(text.replace(needle, replacement, 1))
    print("PASS: added host-only IOFree double to the pinned Adreno740 fixture")
else:
    raise SystemExit("Adreno740 host fixture changed: IOFree insertion anchor is absent")
