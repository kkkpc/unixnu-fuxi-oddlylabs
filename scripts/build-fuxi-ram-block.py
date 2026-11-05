#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Build build/ram-block/libRamBlock.a: UniXNU RamBlock's NativeRamBlock for fuxi.

NativeRamBlock (kits/fuxi/NativeRamBlock.cpp and its headers, unchanged copies of UniXNU RamBlock 4be2d7e) derives from the
original IOBlockStorageDevice of the iPadOS 17.7.11 IOStorageFamily. It publishes the RAM disk DarwinBoot hands over
(/chosen/memory-map RAMDisk or PackedRAMDisk) as a block device, so APFS attaches to it and the kernel can root on one of its
volumes. With CONFIG_XNU_NATIVE_RAM_BLOCK=y the native personality starts it (patches/xnu/native-aes-personality.patch) and
build-xnu-4k-baseline.sh force-loads this archive.

UniXNU builds it with build-arm-driver.py RamBlock and binds it with build-virtio-mmio-bindings.py --component RamBlock, which
reads build/storage-abi/interface-audit.json, the audit of an earlier research build that a fresh CI tree does not have. This
script compiles the source with the same flags (the compile record of IOPlatformExpert.cpp and the storage headers that
prepare-storage-headers.py leaves in build/storage-abi/include), applies the same vtable rules, and binds the
IOBlockStorageDevice imports to the kernelcache addresses in scripts/fuxi_storage_abi.py. ci/check-ram-block-bindings.py
checks those addresses and NativeRamBlock's vtable in the kernel that ships. The persistent-store hooks
NativeRamBlock imports weakly (native_ufs_store_*) are provided by the ShengUfs driver itself, as on sheng;
kits/fuxi/FuxiRamBlockStore.cpp held no-store stubs for them until the driver joined the link (Build #28)
and is now an empty translation unit kept so this build's file list is unchanged.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]   # the assembled build tree: scripts are copied into it
OUT = ROOT / 'build/ram-block'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'kits/XnuPrelink'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_prelink import macho
from fuxi_storage_abi import BINDINGS, PURE, SLOTS, STORAGE_SLOTS

KIT = ROOT / 'kits/fuxi'
STORAGE_INCLUDE = ROOT / 'build/storage-abi/include'
FLAGS = ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-c99-designator', '-Wno-reorder-init-list',
         '-Wno-deprecated-enum-enum-conversion', '-Wno-unnecessary-virtual-specifier',
         '-I', ROOT / '.cache/xnu-work/osfmk', '-I', STORAGE_INCLUDE]


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


obj = OUT / 'NativeRamBlock.o'
compile_source(KIT / 'NativeRamBlock.cpp', obj)
store = OUT / 'FuxiRamBlockStore.o'
compile_source(KIT / 'FuxiRamBlockStore.cpp', store)
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
vtable = next(va for name, va, _ in symbols if name == '__ZTV14NativeRamBlock')
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
    if name.startswith(('__ZN14NativeRamBlock', '__ZNK14NativeRamBlock')):
        owned.append(slot)
    elif '20IOBlockStorageDevice' in name:
        require(slot in STORAGE_SLOTS, f'IOBlockStorageDevice method at slot {slot} has no kernelcache implementation')
        require(bindings.get(name, STORAGE_SLOTS[slot]) == STORAGE_SLOTS[slot], f'One address for {name}')
        bindings[name] = STORAGE_SLOTS[slot]
    else:
        # Inherited from IOService: ci/check-ram-block-bindings.py compares the linked table with the original one.
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
archive = OUT / 'libRamBlock.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, obj, OUT / 'original-bindings.o', store])
# The baseline's dual-transport check (active now that the virtio transport is
# linked too) addresses this object by the archive's stem (libRamBlock.a ->
# RamBlock.o) and compares its hash with the report's compiled_object_sha256
# (Build #38). Leave a byte-identical copy under the stem name.
(OUT / 'RamBlock.o').write_bytes(raw)
report = {'source': 'kits/fuxi/NativeRamBlock.cpp', 'original_slots': SLOTS, 'owned_slots': owned,
          'compiled_object_sha256': hashlib.sha256(raw).hexdigest(),
          'bindings': {name: hex(va) for name, va in sorted(bindings.items())}}
(OUT / 'bindings.json').write_text(json.dumps(report, indent=2) + '\n')
print(f'PASS: NativeRamBlock {len(owned)} own slots, {len(bindings)} original storage imports bound; archive {archive.relative_to(ROOT)}')
