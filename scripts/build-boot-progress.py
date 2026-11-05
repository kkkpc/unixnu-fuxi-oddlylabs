#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Build build/boot-progress/libBootProgress.a: the fuxi boot-progress observer.

UniXNU scripts/build-xnu-4k-baseline.sh runs this script when
CONFIG_XNU_BOOT_PROGRESS=y (the guard also requires the native UFS,
owner-root audit and source-corecrypto configuration this board has) and
then force-loads the archive at the kernel link; without it the build
stops at the baseline's line 90 with "No such file or directory" (Build
#40). No tree in this line carries the script - not the board repo, not
OddlyLabs/UniXNU at 6ae4c252, not upstream UniXNU - and sheng's own
scripts/build-boot-progress.py is not reusable: it compiles sheng-only kit
sources (BootFaultProbe, BootWatchdogPolicy, BootDiagExport, AdspFirmware)
that have no fuxi counterpart.

The archive carries weak no-op definitions of the thirteen boot_progress_*
entry points of patches/xnu/zzz-boot-progress.patch's kern/boot_progress.h,
compiled here from kits/fuxi/FuxiBootProgress.c with the bootstrap pass's
startup.o compile record, the same record-replay treatment as the other
fuxi archive builders. The verified UFS driver needs only
boot_progress_poll; the other twelve are the patch's call sites. The
script also asserts every entry point is defined in the object, so a
missing one fails here with its name instead of at the kernel link.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]   # the assembled build tree: scripts are copied into it
OUT = ROOT / 'build/boot-progress'
OUT.mkdir(parents=True, exist_ok=True)

SOURCE = ROOT / 'kits/fuxi/FuxiBootProgress.c'
RECORD = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/startup.o.json'

ENTRY_POINTS = ['_boot_progress_init', '_boot_progress_start', '_boot_progress_active',
                '_boot_progress_bind', '_boot_progress_putc', '_boot_progress_stage',
                '_boot_progress_irq', '_boot_progress_poll', '_boot_progress_user_breakpoint',
                '_boot_progress_user_abort', '_boot_progress_critical_exit',
                '_boot_progress_process_stage', '_boot_progress_exit']


def run(command, **kwargs):
    return subprocess.check_output([str(v) for v in command], timeout=180, **kwargs)


def require(value, message):
    if not value:
        raise SystemExit(message)


require(SOURCE.is_file(), 'kits/fuxi/FuxiBootProgress.c is missing')
require(RECORD.is_file(),
        'bootstrap compile record startup.o.json is missing: run the bootstrap pass first')
record = json.loads(RECORD.read_text().strip().rstrip(','))

obj = OUT / 'FuxiBootProgress.o'
command, i, arguments = [], 0, record['arguments']
while i < len(arguments):
    arg = arguments[i]
    if arg == record['file']:
        command.append(str(SOURCE))
    elif arg == '-o':
        command += ['-o', str(obj)]
        i += 1
    elif arg in ('-MF', '-MT', '-MJ'):
        i += 1
    elif arg == '-Xclang' and i + 1 < len(arguments) and arguments[i + 1].startswith('-W'):
        i += 1
    elif arg == '-D' and i + 1 < len(arguments) and arguments[i + 1].startswith('XNU_BOOT_PROGRESS='):
        i += 1
    elif not arg.startswith(('-W', '-DXNU_BOOT_PROGRESS=')):
        command.append(arg)
    i += 1
command += ['-DXNU_BOOT_PROGRESS=1', '-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror']
run(command, cwd=record['directory'])

listing = run(['xcrun', 'nm', '-g', str(obj)], text=True)
defined = {fields[-1] for line in listing.splitlines()
           if len(fields := line.split()) >= 3 and fields[1] != 'U'}
require(set(ENTRY_POINTS) <= defined,
        f"boot-progress archive is missing entry points: {sorted(set(ENTRY_POINTS) - defined)}")

archive = OUT / 'libBootProgress.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', str(archive), str(obj)])
(OUT / 'build-report.json').write_text(json.dumps({
    'source': 'kits/fuxi/FuxiBootProgress.c',
    'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'object_sha256': hashlib.sha256(obj.read_bytes()).hexdigest(),
    'entry_points': sorted(ENTRY_POINTS),
}, indent=2) + '\n')
