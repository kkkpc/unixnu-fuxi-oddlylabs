#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Bind build/virtio-mmio-block's NativeVirtioBlock for fuxi.

The VirtioMmioBlock component itself is built by UniXNU's build-arm-driver.py
(the catalog step in board.toml); what remains is the step UniXNU performs with
build-virtio-mmio-bindings.py, which reads build/storage-abi/interface-audit.json
- the recorded audit of an earlier maintainer research build (it is produced
from a prelink candidate and live debugger metadata, not by any build step), so
a fresh CI tree does not have it. This script applies the same vtable rules as
scripts/build-fuxi-ram-block.py and binds the IOBlockStorageDevice imports to
the kernelcache addresses in scripts/fuxi_storage_abi.py: it audits the
compiled NativeVirtioBlock.o, emits original-bindings.o, re-archives
libVirtioMmioBlock.a from the object plus the bindings, and writes
bindings.json in the shape build-xnu-4k-baseline.sh's dual-transport check
consumes (it compares this archive's bindings with the RAM block's - the same
recorded data, so they agree - and links the RAM transport object against
these definitions).
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]   # the assembled build tree: scripts are copied into it
OUT = ROOT / 'build/virtio-mmio-block'
sys.path.insert(0, str(ROOT / 'kits/XnuPrelink'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_prelink import macho
from fuxi_storage_abi import BINDINGS, PURE, SLOTS, STORAGE_SLOTS

MANGLED = '17NativeVirtioBlock'


def run(command, **kwargs):
    return subprocess.check_output([str(v) for v in command], timeout=180, **kwargs)


def require(value, message):
    if not value:
        raise SystemExit(message)


obj = OUT / 'NativeVirtioBlock.o'
require(obj.is_file(), 'build/virtio-mmio-block/NativeVirtioBlock.o is missing: the VirtioMmioBlock component step runs first')
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
vtable = next(va for name, va, _ in symbols if name == '__ZTV' + MANGLED)
relocations = {}
for segment in info['segments']:
    for section in segment['sections']:
        if section['va'] <= vtable < section['va'] + section['size']:
            at, count = struct.unpack_from('<2I', raw, section['command_offset'] + 56)
            for i in range(count):
                offset, bits = struct.unpack_from('<2I', raw, at + i * 8)
                if bits >> 27 & 1 and bits >> 28 == 0 and bits >> 25 & 3 == 3:
                    relocations[section['va'] + offset] = symbols[bits & 0xffffff][0]
entries = [relocations.get(vtable + 16 + i * 8) for i in range(SLOTS)]
require(all(entries) and vtable + 16 + SLOTS * 8 not in relocations and '___cxa_pure_virtual' not in entries,
        'Concrete block class has missing, additional or pure virtual methods')
bindings = {}
owned = []
for slot, name in enumerate(entries):
    if name.startswith(('__ZN' + MANGLED, '__ZNK' + MANGLED)):
        owned.append(slot)
    elif '20IOBlockStorageDevice' in name:
        require(slot in STORAGE_SLOTS, f'IOBlockStorageDevice method at slot {slot} has no kernelcache implementation')
        require(bindings.get(name, STORAGE_SLOTS[slot]) == STORAGE_SLOTS[slot], f'One address for {name}')
        bindings[name] = STORAGE_SLOTS[slot]
    else:
        # Inherited from IOService, exactly as in build-fuxi-ram-block.py's audit.
        require(slot < 168 and slot not in STORAGE_SLOTS, f'IOService method expected at slot {slot}')
require(set(PURE) <= set(owned) and {0, 1} <= set(owned), 'A required transport operation or the destructors are not implemented')
undefined = {n for n, _, k in symbols if k == 1 and 'IOBlockStorageDevice' in n}
# The abstract D1 and D0 of the original are brk traps: only the base D2 may be called.
require(not any(re.search(r'IOBlockStorageDeviceD[01]Ev$', n) for n in undefined), 'Concrete driver must not invoke abstract destruction')
for name in undefined - set(bindings):
    require(name in BINDINGS, f'Unqualified original storage import {name}')
    bindings[name] = BINDINGS[name]
require(undefined == set(bindings), 'All and only actual original storage imports bound')
asm = OUT / 'original-bindings.S'
asm.write_text(''.join(f'.globl {name}\n.set {name}, {va:#x}\n' for name, va in sorted(bindings.items())))
sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk, '-c', asm, '-o', OUT / 'original-bindings.o'])
archive = OUT / 'libVirtioMmioBlock.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, obj, OUT / 'original-bindings.o'])
# The baseline's dual-transport check addresses each transport's object by its
# archive's stem (libVirtioMmioBlock.a -> VirtioMmioBlock.o) and compares its
# hash with bindings.json's compiled_object_sha256 (Build #38). The compiled
# object is NativeVirtioBlock.o; leave a byte-identical copy under the stem
# name so the check reads the same bytes it audited.
shutil.copyfile(obj, OUT / 'VirtioMmioBlock.o')
report = {'compiled_object_sha256': hashlib.sha256(raw).hexdigest(),
          'virtual_methods_checked': SLOTS,
          'concrete_overrides': len(owned),
          'bindings': {name: hex(va) for name, va in sorted(bindings.items())},
          'source': 'build-arm-driver.py VirtioMmioBlock object, bound from scripts/fuxi_storage_abi.py',
          'original_code_modified': False,
          'actual_io_qualified': False}
(OUT / 'bindings.json').write_text(json.dumps(report, indent=2) + '\n')
print(f'PASS: NativeVirtioBlock {len(owned)} own slots, {len(bindings)} original storage imports bound; archive {archive.relative_to(ROOT)}')
