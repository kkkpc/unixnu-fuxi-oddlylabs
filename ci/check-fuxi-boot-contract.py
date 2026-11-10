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
    line = " ".join(args)
    line_bytes = len(line.encode("ascii"))
    if line_bytes > 1000:
        fail(f"kernel command line is {line_bytes} bytes; UniXNU payload limit is 1000")

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
        "offline-legacy-unit-scale": "3",
        "sheng-dpu": "3",
        "sheng-backlight": "1",
        "fuxi-backlight": "dsi",
        "fuxi-touch-stage": "4",
        "fuxi-touch-hw": "7",
        "sheng-cpufreq": "4",
        "offline-key-events": "1",
        "-apfs_shared_datavolume": None,
        "-no_slto_panic": None,
        "sheng-gpu-metal": "1",
        "sheng-fb-gpu": "1",
        "sheng-gpu-addon": "1",
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
    print(f"PASS: fuxi boot contract keeps panic evidence and V2 parity; kernel args {line_bytes}/1000 bytes")


if __name__ == "__main__":
    main()
