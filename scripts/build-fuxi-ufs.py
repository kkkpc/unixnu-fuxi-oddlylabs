#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Build build/sheng-ufs/libShengUfs.a: the ShengUfs UFS root driver for fuxi, device-side.

The sources in package/ufs/ (linked into the build tree as kits/fuxi/ufs/, like every
device package source) are copies of UniXNU/ShengUfs (driver files unchanged since
99d8bcd; copied from the af14068 tree, BSD-2-Clause, see the LICENSE file beside them),
with three fuxi patches in NativeUfs.cpp: the read-path timing calls use timerTicks and
native_ufs_read_ticks outside the NATIVE_VERIFIED_BLOCK region that defines them, which
only the verified configuration upstream builds ever compiles, so the calls are gated the
same way (Build #14 errors); startRoot's identity validation returns false
unconditionally without the define ("Root publication requires owner verification in
every build"), which would publish nothing at all in this configuration, so its
unverified branch returns true instead — window distinctness is already enforced by
ufsBuildRootPlan, and per-block verification is what the dropped owner-root chain would
have added (owner decision, 2026-11-04); and the publisher's per-window media wait
matches IOMedia by the signed volume UUID that only the verified branch of validate()
fills, so without the define the wait could never succeed and publication timed out at
the first window (SystemOS), discarding the OS window unstarted (device, 2026-11-05:
the rootmatch boot's "Failed to mount root device"), so with an empty UUID the wait
falls back to ancestry alone — any IOMedia whose ancestor chain reaches the window
counts as its published media, and verified builds are unchanged. They are built here instead of through the catalog component because this
script also replays the board's storage ABI audit (below) and compiles the board's
package/SourceRootBinding.cpp into the same archive; the compile flags mirror the
catalog recipe (build-arm-driver.py for NativeUfs: -DNATIVE_VERIFIED_BLOCK=1 and
-DNATIVE_VERIFIED_BLOCK_MULTI_POLICY=1 with the VerifiedRoot include). The policy data
that mode references (verified_root_policies / verified_root_key /
verified_root_policy_count, plus the vr_* implementation in kits/VerifiedRoot) is
supplied by the probe bundle archive that scripts/build-fuxi-owner-root.py generates
earlier in the build; the owner-policy pipeline it runs is frozen to the IPSW payload
(its root UUID and image digests are this iPadOS 17.7.11 image's own constants), not
to the sheng board. Owner decision (2026-11-05): the full owner-root trust chain is
ported — with it off, the device mounted the UFS root and panicked in bsd_init
("rootvp not authenticated after mounting"), because on a non-macOS target the
FSIOC_KERNEL_ROOTAUTH check passes only through the owner authorization the chain
provides. The binding object supplies native_verified_block_root_authorized, which
bsd_init consults through the offline-owner-root-binding-audit patch; it answers
from native_ufs_block_authenticates in the driver object. The catalog ShengUfs
component is therefore not selected; CONFIG_XNU_NATIVE_UFS=y keeps the native
personality and build-xnu-4k-baseline.sh force-loads this archive from its fixed path.

The compile replays the IOPlatformExpert compile record with the storage headers that
prepare-storage-headers.py leaves in build/storage-abi/include, exactly like
build-fuxi-ram-block.py, and audits NativeUfsBlock's IOBlockStorageDevice imports
against the kernelcache addresses in scripts/fuxi_storage_abi.py the same way. The
alias definitions themselves are emitted once per kernel, by the RAM block build:
defining them here too gave duplicate symbols at the kernel link (Build #28).
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]   # the assembled build tree: scripts are copied into it
OUT = ROOT / 'build/sheng-ufs'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'kits/XnuPrelink'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_prelink import macho
from fuxi_storage_abi import BINDINGS, PURE, SLOTS, STORAGE_SLOTS

KIT = ROOT / 'kits/fuxi/ufs'
STORAGE_INCLUDE = ROOT / 'build/storage-abi/include'
FLAGS = ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-c99-designator', '-Wno-reorder-init-list',
         '-Wno-deprecated-enum-enum-conversion', '-Wno-unnecessary-virtual-specifier', '-mgeneral-regs-only',
         '-I', ROOT / '.cache/xnu-work/osfmk', '-I', STORAGE_INCLUDE,
         '-I', ROOT / 'kits/VerifiedRoot/include', '-DNATIVE_VERIFIED_BLOCK=1', '-DNATIVE_VERIFIED_BLOCK_MULTI_POLICY=1']


def run(command, **kwargs):
    return subprocess.check_output([str(v) for v in command], timeout=180, **kwargs)


def require(value, message):
    if not value:
        raise SystemExit(message)


require((STORAGE_INCLUDE / 'IOKit/storage/IOBlockStorageDevice.h').is_file(),
        'build/storage-abi/include is missing: the kernel step prepares it from refer/IOStorageFamily')
record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))


def compile_source(source, obj):
    command, i, arguments = [], 0, record['arguments']
    while i < len(arguments):
        arg = arguments[i]
        if arg == record['file']:
            command.append(source)
        elif arg == '-o':
            command += ['-o', obj]
            i += 1
        elif arg in ('-MF', '-MT', '-MJ'):
            i += 1
        elif arg == '-Xclang' and arguments[i + 1].startswith('-W'):
            i += 1
        elif not arg.startswith('-W'):
            command.append(arg)
        i += 1
    run(command + FLAGS, cwd=record['directory'])


obj = OUT / 'NativeUfs.o'
compile_source(KIT / 'NativeUfs.cpp', obj)
raw = obj.read_bytes()
info = macho(raw)
require(info['kind'] == 1, 'Require actual ARM64 subtype-0 Mach-O object')
build_version = [struct.unpack_from('<2I', raw, at + 8) for cmd, at, _ in info['commands'] if cmd == 0x32]
require(build_version == [(2, 0x110000)], 'Require iOS17 build target')
sym_at = next(at for cmd, at, _ in info['commands'] if cmd == 2)
at, count, strings, _ = struct.unpack_from('<4I', raw, sym_at + 8)
symbols = []
for i in range(count):
    ix, kind, _, _, address = struct.unpack_from('<IBBHQ', raw, at + i * 16)
    symbols.append((raw[strings + ix:raw.index(b'\0', strings + ix)].decode(), address, kind))
vtable = next(va for name, va, _ in symbols if name == '__ZTV14NativeUfsBlock')
relocations = {}
for segment in info['segments']:
    for section in segment['sections']:
        if section['va'] <= vtable < section['va'] + section['size']:
            at, count = struct.unpack_from('<2I', raw, section['command_offset'] + 56)
            for i in range(count):
                offset, bits = struct.unpack_from('<2I', raw, at + i * 8)
                if bits >> 27 & 1 and bits >> 28 == 0 and bits >> 25 & 3 == 3:
                    relocations[section['va'] + offset] = symbols[bits & 0xffffff][0]
entries = []
while vtable + 16 + len(entries) * 8 in relocations and len(entries) < 280:
    entries.append(relocations[vtable + 16 + len(entries) * 8])
require(len(entries) >= SLOTS, 'NativeUfsBlock vtable is shorter than the IOBlockStorageDevice layout')
require('___cxa_pure_virtual' not in entries, 'Concrete block class still has pure virtual methods')
bindings = {}
owned = []
for slot, name in enumerate(entries):
    if name.startswith(('__ZN14NativeUfsBlock', '__ZNK14NativeUfsBlock')):
        owned.append(slot)
    elif '20IOBlockStorageDevice' in name:
        require(slot in STORAGE_SLOTS, f'IOBlockStorageDevice method at slot {slot} has no kernelcache implementation')
        require(bindings.get(name, STORAGE_SLOTS[slot]) == STORAGE_SLOTS[slot], f'One address for {name}')
        bindings[name] = STORAGE_SLOTS[slot]
    else:
        # Inherited from IOService: the linked table is compared with the original one the same way as the RAM block's.
        require(slot < 168 and slot not in STORAGE_SLOTS, f'IOService method expected at slot {slot}, got {name}')
require(set(PURE) <= set(owned) and {0, 1} <= set(owned), 'A required transport operation or the destructors are not implemented')
undefined = {n for n, _, k in symbols if k == 1 and 'IOBlockStorageDevice' in n}
# The abstract D1 and D0 of the original are brk traps: only the base D2 may be called.
require(not any(re.search(r'IOBlockStorageDeviceD[01]Ev$', n) for n in undefined), 'Concrete driver must not invoke abstract destruction')
for name in undefined - set(bindings):
    require(name in BINDINGS, f'Unqualified original storage import {name}')
    bindings[name] = BINDINGS[name]
require(undefined == set(bindings), 'All and only actual original storage imports bound')
# The original IOBlockStorageDevice aliases are defined exactly once per kernel, by
# build-fuxi-ram-block.py's original-bindings.o (the same addresses, from
# scripts/fuxi_storage_abi.py; the kernel build script states the same one-alias
# rule for the virtio transport). Defining them here as well gave 17 duplicate
# symbols at the kernel link in Build #28, so this archive carries only the driver
# object and NativeUfs.o's audited imports resolve against the RAM block's aliases.
# The audited set is still recorded in bindings.json below.
# The board's root binding (package/SourceRootBinding.cpp, linked into the tree as
# kits/fuxi/) supplies native_verified_block_root_authorized and its two companions,
# which the owner-root bsd_init patch consults after mounting; it answers through
# native_ufs_block_authenticates in the driver object above.
binding_obj = OUT / 'SourceRootBinding.o'
compile_source(ROOT / 'kits/fuxi/SourceRootBinding.cpp', binding_obj)
binding_raw = binding_obj.read_bytes()
binding_info = macho(binding_raw)
require(binding_info['kind'] == 1, 'Require actual ARM64 subtype-0 Mach-O binding object')
b_sym_at = next(at for cmd, at, _ in binding_info['commands'] if cmd == 2)
b_at, b_count, b_strings, _ = struct.unpack_from('<4I', binding_raw, b_sym_at + 8)
binding_defined = set()
for i in range(b_count):
    ix, kind, _, _, _ = struct.unpack_from('<IBBHQ', binding_raw, b_at + i * 16)
    if kind != 1:
        binding_defined.add(binding_raw[b_strings + ix:binding_raw.index(b'\0', b_strings + ix)].decode())
for required in ('_native_verified_block_root_authorized', '_native_verified_block_manifest_sha384',
                 '_native_verified_block_volume_device'):
    require(required in binding_defined, f'SourceRootBinding object does not define {required}')
archive = OUT / 'libShengUfs.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, obj, binding_obj])
report = {'source': 'kits/fuxi/ufs/NativeUfs.cpp', 'verified_block': True,
          'compiled_object_sha256': hashlib.sha256(raw).hexdigest(),
          'binding_object_sha256': hashlib.sha256(binding_raw).hexdigest(),
          'original_slots': len(entries), 'owned_slots': owned,
          'bindings': {name: hex(va) for name, va in sorted(bindings.items())}}
(OUT / 'bindings.json').write_text(json.dumps(report, indent=2) + '\n')
print(f'PASS: NativeUfsBlock {len(owned)} own slots, {len(bindings)} original storage imports bound; archive {archive.relative_to(ROOT)}')
