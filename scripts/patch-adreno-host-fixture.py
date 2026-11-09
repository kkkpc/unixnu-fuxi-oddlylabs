#!/usr/bin/env python3
"""Backport the current upstream optional-replay behavior to the pinned Adreno Metal builder.

The fast bring-up image needs the target iOS Turnip library and Metal plugin. The
host replay capture is diagnostic-only in current upstream (--no-replay), so the
pinned 6ae4c252 tree is adapted to omit gen-turnip-replay.py and any stale
TurnipReplay.h. No device-side GPU source is changed.
"""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--tree", type=Path, required=True, help="resolved UniXNU target tree")
args = parser.parse_args()
root = args.tree.resolve()
builder = root / "scripts/build-adreno-metal-plugin.py"

if not builder.is_file():
    raise SystemExit(f"Adreno Metal builder missing: {builder}")

text = builder.read_text()
marker = "optional Turnip host replay capture skipped for fuxi bring-up"
legacy = """# Turnip's first submission, recorded on the host, for the plugin's prefix replay (build/turnip-smoke/TurnipReplay.h).
subprocess.run(['python3', ROOT / 'scripts/gen-turnip-replay.py'], check=True)
"""
replacement = """# fuxi fast bring-up: current upstream exposes this host replay as optional diagnostics (--no-replay).
# The target plugin accepts an absent TurnipReplay.h through its existing optional include path.
(ROOT / 'build/turnip-smoke/TurnipReplay.h').unlink(missing_ok=True)
print('PASS: optional Turnip host replay capture skipped for fuxi bring-up')
"""

if marker in text:
    print("PASS: pinned Adreno Metal builder already skips the optional replay capture")
elif legacy in text:
    builder.write_text(text.replace(legacy, replacement, 1))
    print("PASS: backported upstream --no-replay behavior to the pinned Adreno Metal builder")
else:
    raise SystemExit("Adreno Metal builder changed: replay-call anchor is absent")
