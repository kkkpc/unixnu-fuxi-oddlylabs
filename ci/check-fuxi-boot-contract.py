#!/usr/bin/env python3
"""Check the fuxi boot contract before a kernel or image is published.

The phone is being used as a persistent A-slot boot target.  A panic must
therefore remain observable and must never be turned into an automatic reset
or fastboot transition by the bring-up helpers.
"""
from pathlib import Path
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main():
    board = tomllib.loads((ROOT / "board.toml").read_text())
    args = board.get("payload", {}).get("kernel_args", [])
    forbidden = {
        "sheng-autoreset": "automatic recovery reset",
        "fuxi-panic-fastboot": "panic-to-fastboot recovery",
        "fuxi-touch-panic": "diagnostic panic reset loop",
    }
    for argument in args:
        name = argument.removeprefix("-").split("=", 1)[0]
        if name in forbidden:
            fail(f"{forbidden[name]} is enabled in board.toml: {argument}")
    required = {
        "native-fuxi-ufs-root": "1",
        "sheng-gpu-addon": "1",
        "-no_slto_panic": None,
    }
    present = {argument.split("=", 1)[0]: argument.split("=", 1)[1] if "=" in argument else None
               for argument in args}
    for name, value in required.items():
        if name not in present or (value is not None and present[name] != value):
            fail(f"required boot argument is missing or changed: {name}={value or ''}")

    source = (ROOT / "package/drivers/QcomXnuUsbDebug/kernel/QcomXnuUsbDebug.c").read_text()
    if not re.search(r"#define\s+QUD_CONTROL_REBOOT\s+0", source):
        fail("QcomXnuUsbDebug does not default QUD_CONTROL_REBOOT to 0")
    build = (ROOT / "scripts/build-fuxi-usb-debug.py").read_text()
    if "-DQUD_CONTROL_REBOOT=0" not in build:
        fail("production USB debug archive is not compiled with QUD_CONTROL_REBOOT=0")
    print("PASS: fuxi boot contract keeps panic evidence, UFS root and GPU addon enabled")


if __name__ == "__main__":
    main()
