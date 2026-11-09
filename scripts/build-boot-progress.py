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

It also carries the watchdog policy the same patch calls from
load_init_program when XNU_OWNER_DATA_MOUNT and XNU_BOOT_PROGRESS are
both on: sheng_boot_watchdog_policy, compiled here from
kits/fuxi/BootWatchdogPolicy.c with the bootstrap pass's kern_exec.o
compile record (the BSD-side record, as the policy uses the BSD syscalls;
sheng's own builder does the same). The policy source is the port in
package/BootWatchdogPolicy.c; the script asserts the symbol is defined,
so a missing policy fails here instead of at the kernel link (Build #51:
exactly that one undefined symbol, after the Data stage flipped
DATA_MOUNT on). Sheng's other kit sources (BootFaultProbe, BootDiagExport,
AdspFirmware) still have no fuxi counterpart and are not compiled here.
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
POLICY_SOURCE = ROOT / 'kits/fuxi/BootWatchdogPolicy.c'
POLICY_RECORD = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT/kern_exec.o.json'
EXPORT_SOURCE = ROOT / 'kits/fuxi/FuxiBootLogExport.c'

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

# The watchdog policy: same record-replay shape as sheng's builder, but
# from this tree's kern_exec.o record. The record exists by now: the
# bootstrap pass compiled kern_exec.o before failing at the link, and this
# script only runs on the final pass (XNU_BOOT_PROGRESS=0 in bootstrap).
require(POLICY_SOURCE.is_file(), 'kits/fuxi/BootWatchdogPolicy.c is missing')
require(POLICY_RECORD.is_file(),
        'bootstrap compile record kern_exec.o.json is missing: run the bootstrap pass first')
policy_record = json.loads(POLICY_RECORD.read_text().strip().rstrip(','))
policy_obj = OUT / 'BootWatchdogPolicy.o'
policy_command, j, policy_arguments = [], 0, policy_record['arguments']
while j < len(policy_arguments):
    arg = policy_arguments[j]
    if arg == policy_record['file']:
        policy_command.append(str(POLICY_SOURCE))
    elif arg == '-o':
        policy_command += ['-o', str(policy_obj)]
        j += 1
    elif arg in ('-MF', '-MT', '-MJ'):
        j += 1
    elif arg == '-Xclang' and j + 1 < len(policy_arguments) and policy_arguments[j + 1].startswith('-W'):
        j += 1
    elif not arg.startswith('-W'):
        policy_command.append(arg)
    j += 1
policy_command += ['-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror']
run(policy_command, cwd=policy_record['directory'])

policy_listing = run(['xcrun', 'nm', '-g', str(policy_obj)], text=True)
policy_defined = {fields[-1] for line in policy_listing.splitlines()
                  if len(fields := line.split()) >= 3 and fields[1] != 'U'}
require('_sheng_boot_watchdog_policy' in policy_defined,
        'boot-progress archive is missing _sheng_boot_watchdog_policy')

# V2's ordered NativeAdreno pipeline-cache export, without V2's background
# logger or any reset/autoreset code.  It uses only the bounded NativeUfs
# export window and is compiled from the same osfmk record as the observer.
require(EXPORT_SOURCE.is_file(), 'kits/fuxi/FuxiBootLogExport.c is missing')
export_obj = OUT / 'FuxiBootLogExport.o'
export_command, k, export_arguments = [], 0, record['arguments']
while k < len(export_arguments):
    arg = export_arguments[k]
    if arg == record['file']:
        export_command.append(str(EXPORT_SOURCE))
    elif arg == '-o':
        export_command += ['-o', str(export_obj)]
        k += 1
    elif arg in ('-MF', '-MT', '-MJ'):
        k += 1
    elif arg == '-Xclang' and k + 1 < len(export_arguments) and export_arguments[k + 1].startswith('-W'):
        k += 1
    elif not arg.startswith('-W'):
        export_command.append(arg)
    k += 1
export_command += ['-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror']
run(export_command, cwd=record['directory'])
export_listing = run(['xcrun', 'nm', '-g', str(export_obj)], text=True)
require('_boot_log_export_put' in {fields[-1] for line in export_listing.splitlines()
                                   if len(fields := line.split()) >= 3 and fields[1] != 'U'},
        'boot-progress archive is missing _boot_log_export_put')

archive = OUT / 'libBootProgress.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', str(archive), str(obj), str(policy_obj), str(export_obj)])
(OUT / 'build-report.json').write_text(json.dumps({
    'source': 'kits/fuxi/FuxiBootProgress.c',
    'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'object_sha256': hashlib.sha256(obj.read_bytes()).hexdigest(),
    'entry_points': sorted(ENTRY_POINTS),
    'policy_source': 'kits/fuxi/BootWatchdogPolicy.c',
    'policy_source_sha256': hashlib.sha256(POLICY_SOURCE.read_bytes()).hexdigest(),
    'policy_object_sha256': hashlib.sha256(policy_obj.read_bytes()).hexdigest(),
    'policy_symbol': '_sheng_boot_watchdog_policy',
    'export_source': 'kits/fuxi/FuxiBootLogExport.c',
    'export_source_sha256': hashlib.sha256(EXPORT_SOURCE.read_bytes()).hexdigest(),
    'export_object_sha256': hashlib.sha256(export_obj.read_bytes()).hexdigest(),
    'export_symbol': '_boot_log_export_put',
    'automatic_reboot': False,
}, indent=2) + '\n')
