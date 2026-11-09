#!/usr/bin/env python3
"""Seed the audited 21H461 Legacy framebuffer ABI before the runtime audit."""
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/fuxi-21H461-mobile-graphics-legacy-abi.json"
OUTPUT = ROOT / "build/display-analysis/mobile-graphics-legacy-abi.json"

if not SOURCE.is_file():
    raise SystemExit(f"audited Legacy ABI baseline missing: {SOURCE}")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
if not OUTPUT.exists():
    shutil.copyfile(SOURCE, OUTPUT)
print(f"seeded {OUTPUT.relative_to(ROOT)} from the qualified 21H461 ABI baseline")
