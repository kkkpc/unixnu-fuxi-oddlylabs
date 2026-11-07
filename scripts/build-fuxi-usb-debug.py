#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Build build/qcom-usb-debug/libQcomXnuUsbDebug.a: the QcomXnuUsbDebug USB log channel for fuxi.

QcomXnuUsbDebug (ljhhkx529/QcomXnuUsbDebug 3fec41c, vendored at kits/fuxi/drivers/QcomXnuUsbDebug with one
recorded consumer adaptation, below) is a DWC3 CDC-ACM transport that tees the kernel's
printf/kprintf/IOLog/panic output to a host over USB from just after ExitBootServices, with a small control
channel (status, on-demand screenshot; the two reboot verbs answer ERR/unsupported in this log-only
integration). It replaces the panic-string photograph as this board's boot evidence channel.

The module's control REBOOT / REBOOT-FASTBOOT commit path calls an extern qcom_reset_request: the reset
layer the consumer kernel is expected to supply (the author's commits describe the design; no definition
exists in the module, its patch sets, or the UniXNU / sm8550-common / sheng trees, and the module's own
build.py audit is archive-local with a fixed allowlist, so a kernel-side definition could not pass it
either). This board integrates the log channel first and defers the reset layer as its own stage, so the
vendored kernel/QcomXnuUsbDebug.c carries a QUD_CONTROL_REBOOT guard (default 1, upstream behaviour
bit-for-bit) and this wrapper appends -DQUD_CONTROL_REBOOT=0 to its adapted copy of the compile record:
both reboot verbs answer ERR/unsupported - never a queued success for a reset that will not happen, and a
fastboot request is never downgraded to a plain reset - and the archive carries no unresolved reset
reference. The adaptation is insertion-only apart from the one install expression it prefixes, and is recorded in porting.toml (diagnostics).

The module's own scripts/build.py does the compiling: it takes the pe_kprintf compile record of the real XNU
build (the same records the other board builders consume), compiles the module's five units
(kernel/QcomXnuUsbDebug.c, kernel/QcomUsbScreenshot.c, usb/Dwc3.c, soc/QcomUsbQualify.c,
soc/QcomUsbDmaDomain.c) with the Sm8550 profile, archives them and audits the archive's imports/exports.
build.py insists on a fresh output directory below a tmp/ or .cache/ component, so this wrapper stages the
build in .cache/qud-module-build and publishes the archive at build/qcom-usb-debug/, the path
configs/fuxi_defconfig's CONFIG_XNU_EXTRA_LD_ARCHIVES force-loads.

The six XNU hook units are patched by patches/xnu/qcom-usb-debug-console.patch and
qcom-usb-debug-worker.patch (the consumer-side darwin24 profile: upstream's darwin22 set retargeted to
xnu-10063.141.1; printf.c re-expresses the disableConsoleOutput guard that 10063 moved into console_write,
serial_console.c captures ahead of that early return). The kernel build compiles those units with
-DXNU_QCOM_USB_DEBUG=1 and this module's include path (the Build kernel step's XNU_EXTRA_CFLAGS in
.github/workflows/build.yml). Without the define the patches are inert and this archive is simply linked
unreferenced. Boot arguments qcom-usb-debug=1 and qcom-usb-ctl=1 (board.toml) enable the backend and the
control channel at runtime.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the assembled build tree: scripts are copied into it
MODULE = ROOT / 'kits/fuxi/drivers/QcomXnuUsbDebug'
OUT = ROOT / 'build/qcom-usb-debug'
STAGE = ROOT / '.cache/qud-module-build'


def require(value, message):
    if not value:
        raise SystemExit(message)


require((MODULE / 'scripts/build.py').is_file(),
        'the vendored QcomXnuUsbDebug module is missing at kits/fuxi/drivers/QcomXnuUsbDebug')
records_dir = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/pexpert/DEVELOPMENT'
record = records_dir / 'pe_kprintf.o.json'
if not record.is_file():
    candidates = sorted(records_dir.glob('pe_kprintf*.json'))
    require(candidates, 'no pe_kprintf compile record: the kernel bootstrap pass did not leave one')
    record = candidates[0]

# The module build refuses an existing output directory; the staging path is ours alone.
shutil.rmtree(STAGE, ignore_errors=True)
STAGE.mkdir(parents=True)
# Log-only integration (see the docstring): build the module units from an adapted copy of the record
# that compiles the control reboot commit path out. build.py hashes the record it is given, so the
# adaptation is visible in its build report like any other input.
record_data = json.loads(record.read_bytes().decode().rstrip().rstrip(','))
record_data['arguments'] = [*record_data['arguments'], '-DQUD_CONTROL_REBOOT=0']
adapted = STAGE / 'pe_kprintf.qud.json'
adapted.write_text(json.dumps(record_data))
build_out = STAGE / 'build'
subprocess.run([sys.executable, str(MODULE / 'scripts/build.py'),
                '--compile-record', str(adapted),
                '--soc', 'soc/Sm8550.h',
                '--output', str(build_out)], check=True)
built = build_out / 'libQcomXnuUsbDebug.a'
require(built.is_file(), 'the module build produced no libQcomXnuUsbDebug.a')
OUT.mkdir(parents=True, exist_ok=True)
archive = OUT / 'libQcomXnuUsbDebug.a'
shutil.copyfile(built, archive)
print(f'PASS: QcomXnuUsbDebug archive {archive.relative_to(ROOT)} '
      f'(module build report .cache/qud-module-build/build/build-report.json)')
