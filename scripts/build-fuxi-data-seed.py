#!/usr/bin/env python3
"""Build this board's scratch Data seed in the image job (macOS runner only).

The seed is a 256 MiB APFS container image whose single volume (OwnerData)
carries the OS image's initial private/var tree and the pinned scratch volume
UUID 18AB5557-DC2D-469B-8758-855E60F5B0DF - the value fuxi_defconfig sets as
CONFIG_XNU_OWNER_DATA_VOLUME_UUID (the value upstream pins in
scripts/build-cpu-desktop-kernel.py and its RAM-data checkpoints check for).
The payload step packs it as Payloads/scratch-data.img; DarwinBoot hands it to
the kernel as a RAM disk, and the scratch Data mount
(patches/xnu-12377/offline-owner-systemos-mount.patch) selects the volume
through NativeRamBlock's native_ram_block_volume_seed - the unique IOMedia
whose UUID property equals the pinned value and whose provider chain contains
the RAM block - and mounts it writable at /private/var before launchd is
exec'd (success: native_owner_data_stage==4, status==0, readonly==0).

The var-tree recipe is UniXNU's scripts/prepare-owner-data-fixture.py, with
two changes: the container is 256 MiB instead of 32 MiB, and the volume UUID
is rewritten to the pinned value. A freshly formatted volume's UUID is
random, and no macOS tool sets it at creation time; in the image the UUID's
raw bytes occur only in the volume superblock's checkpoint copies (measured
on this IPSW's SystemOS image: five occurrences, all in APFS
volume-superblock blocks, in-block offset 240), so the script replaces every
occurrence and repairs each touched block's Fletcher-64 object checksum.
Both checksum invariants were measured on genuine APFS objects: the full
block's first Fletcher sum is zero, and the stored high half equals the
second sum computed with the checksum field zeroed. After patching, the
image is attached again and diskutil must report the pinned VolumeUUID -
the APFS driver's own acceptance - before the seed is used.

The seed is guest-mutable and unsigned by design (upstream's checkpoints
record initial_seed_signature_verified=false for the same construction);
nothing about it is trusted, it is only found. The board's persistent store
stays off (package/FuxiRamBlockStore.cpp answers the store hooks with no
store), so the Data volume is per-boot ephemeral: writes live in RAM only.
The OS image is an input only; it is attached read-only and never modified.

The same patch pass also normalizes the volume's incompatible-feature word.
A macOS 26 newfs_apfs volume declares APFS_INCOMPAT_CASE_INSENSITIVE (0x1)
alone; both IPSW volumes of this OS declare APFS_INCOMPAT_NORMALIZATION_
INSENSITIVE (0x8) and neither declares 0x1 (SystemOS 0x28, System 0x8) - no
Apple-shipped volume uses the 0x1-only combination. The chain47 device boot
(2026-11-06) hung with a permanently black screen inside the scratch Data
mount's synchronous APFS mount() call - the only no-timeout call in the Data
path (the seed lookup, the boot-manifest publish and every glue failure were
audited to fail loudly onto a panic page, and the sibling chain46 image
booted normally on the same unit minutes later) - so the seed now declares
0x8 exactly like the volumes this kernel mounts, and the patch refuses any
other starting value instead of guessing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import uuid

OS_DMG_SHA256 = '3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d'
OS_UUID = '04769D26-2CA0-4825-B443-E2E5F88300F2'
LAUNCHD_SHA256 = '8cec9a3c44a443b08e977ccc5d577850316ad428c575dc01f09b018dbd5b6a25'
TARGET_UUID = '18AB5557-DC2D-469B-8758-855E60F5B0DF'
BLOCK = 4096
OBJECT_TYPE_APFS = 0x000D  # volume superblock
FLETCHER_MOD = (1 << 32) - 1
APSB_INCOMPAT_OFFSET = 56  # apfs_incompatible_features in the volume superblock
SEED_INCOMPAT_FORMATTER = 0x1  # APFS_INCOMPAT_CASE_INSENSITIVE, as newfs_apfs writes it
SEED_INCOMPAT_TARGET = 0x8  # APFS_INCOMPAT_NORMALIZATION_INSENSITIVE, as the IPSW volumes declare


def run(command, **kwargs):
    print('+', ' '.join(str(part) for part in command), flush=True)
    return subprocess.run([str(part) for part in command], check=True, **kwargs)


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


# --- APFS volume UUID rewriting ---------------------------------------------

def fletcher_sums(words):
    first = second = 0
    for word in words:
        first = (first + word) % FLETCHER_MOD
        second = (second + first) % FLETCHER_MOD
    return first, second


def block_checksums_valid(block):
    """Both measured invariants of a genuine APFS object block."""
    words = struct.unpack('<1024I', block)
    stored = words[0] | (words[1] << 32)
    if fletcher_sums(words)[0] != 0:
        return False
    zeroed = (0, 0) + words[2:]
    return fletcher_sums(zeroed)[1] == (stored >> 32)


def repair_block(block):
    """Restore both checksum invariants of a patched object block."""
    words = list(struct.unpack('<1024I', block))
    zeroed = (0, 0) + tuple(words[2:])
    words[1] = fletcher_sums(zeroed)[1]
    words[0] = (-(words[1] + sum(words[2:]))) % FLETCHER_MOD
    repaired = struct.pack('<1024I', *words)
    require(block_checksums_valid(repaired), 'Internal error: checksum repair did not validate')
    return repaired


def patch_volume_uuid(image, created_uuid, target_uuid=TARGET_UUID):
    """Rewrite every raw occurrence of the created volume UUID to the target.

    Every occurrence must sit in a volume-superblock block; anything else
    aborts instead of guessing. The same pass rewrites each touched
    superblock's incompatible-feature word from the formatter's value to
    SEED_INCOMPAT_TARGET (see the module docstring). Returns (UUID
    occurrences replaced, superblocks normalized).
    """
    source = uuid.UUID(created_uuid).bytes
    target = uuid.UUID(target_uuid).bytes
    require(source != target, 'Created volume already carries the pinned UUID; nothing to do')
    data = bytearray(image.read_bytes())
    require(bytes(data[32:36]) == b'NXSB', 'Seed image is not a raw APFS container (no NXSB)')
    require(created_uuid.upper().encode() not in data and created_uuid.lower().encode() not in data,
            'Created UUID also occurs as text in the seed image; refusing to patch blindly')
    occurrences = []
    index = data.find(source)
    while index != -1:
        occurrences.append(index)
        index = data.find(source, index + 1)
    require(occurrences, 'Created volume UUID not found in the seed image')
    touched = sorted({offset // BLOCK for offset in occurrences})
    for block_index in touched:
        base = block_index * BLOCK
        block = bytes(data[base:base + BLOCK])
        object_type = struct.unpack('<I', block[24:28])[0] & 0xFFFF
        require(object_type == OBJECT_TYPE_APFS,
                f'UUID occurrence in block {block_index} is not a volume superblock '
                f'(object type 0x{object_type:04x}); refusing to patch')
        require(block_checksums_valid(block),
                f'Volume superblock block {block_index} fails its checksum before patching')
        incompat = struct.unpack('<Q', block[APSB_INCOMPAT_OFFSET:APSB_INCOMPAT_OFFSET + 8])[0]
        require(incompat == SEED_INCOMPAT_FORMATTER,
                f'Volume superblock block {block_index} declares incompatible features '
                f'0x{incompat:x}, not the formatter value 0x{SEED_INCOMPAT_FORMATTER:x}; refusing to patch')
    for offset in occurrences:
        data[offset:offset + 16] = target
    for block_index in touched:
        struct.pack_into('<Q', data, block_index * BLOCK + APSB_INCOMPAT_OFFSET, SEED_INCOMPAT_TARGET)
    for block_index in touched:
        base = block_index * BLOCK
        data[base:base + BLOCK] = repair_block(bytes(data[base:base + BLOCK]))
    image.write_bytes(data)
    verify = image.read_bytes()
    require(verify.find(source) == -1, 'Created UUID still present after patching')
    require(verify.count(target) == len(occurrences), 'Pinned UUID occurrence count changed while patching')
    for block_index in touched:
        base = block_index * BLOCK
        block = verify[base:base + BLOCK]
        require(struct.unpack('<Q', block[APSB_INCOMPAT_OFFSET:APSB_INCOMPAT_OFFSET + 8])[0] == SEED_INCOMPAT_TARGET,
                f'Volume superblock block {block_index} does not declare the target incompatible '
                'features after patching')
        require(block_checksums_valid(block),
                f'Volume superblock block {block_index} fails its checksum after patching')
    return len(occurrences), len(touched)


# --- Seed construction --------------------------------------------------------

def attached_system_mount(os_dmg):
    """Attach the OS container read-only; return (whole_device, System mount)."""
    run(['hdiutil', 'attach', '-readonly', '-nobrowse', os_dmg])
    info = plistlib.loads(subprocess.check_output(['hdiutil', 'info', '-plist']))
    entities = next(framework['system-entities'] for framework in info['images']
                    if framework.get('image-path') == str(os_dmg))
    whole_device = next((e['dev-entry'] for e in entities
                         if e.get('content-hint') == 'GUID_partition_scheme'), None)
    require(whole_device, 'Attached OS image has no whole-disk device')
    for entity in entities:
        if 'mount-point' not in entity:
            continue
        volume = plistlib.loads(subprocess.check_output(
            ['diskutil', 'info', '-plist', entity['mount-point']]))
        if volume.get('VolumeUUID') == OS_UUID:
            return whole_device, Path(entity['mount-point'])
    raise SystemExit('Attached OS image has no mounted volume with the System volume UUID')


def copy_var_tree(source, target):
    count = total = 0
    for current, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [name for name in dirs if name != 'staged_system_apps']
        dest = target / Path(current).relative_to(source)
        dest.mkdir(exist_ok=True)
        os.chmod(dest, stat.S_IMODE(Path(current).stat().st_mode))
        for name in list(dirs):
            entry = Path(current) / name
            if entry.is_symlink():
                os.symlink(os.readlink(entry), dest / name)
                dirs.remove(name)
        for name in files:
            entry, out = Path(current) / name, dest / name
            if entry.is_symlink():
                os.symlink(os.readlink(entry), out)
            else:
                shutil.copy2(entry, out)
                count += 1
                total += entry.stat().st_size
    for name in ('keybags', 'mobile/tmp', 'tmp', 'run'):
        (target / name).mkdir(parents=True, exist_ok=True)
    os.chmod(target / 'tmp', 0o1777)
    return count, total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--os-dmg', type=Path, required=True,
                        help='the extracted OS container image (044-76040-038.dmg) from the kernel build cache')
    parser.add_argument('--out', type=Path, default=Path('build/data-seed'))
    parser.add_argument('--size-mib', type=int, default=256)
    args = parser.parse_args()
    require(sys.platform == 'darwin', 'The Data seed is built with hdiutil: macOS only')
    os_dmg = args.os_dmg.resolve()
    require(os_dmg.is_file(), f'OS image not found: {os_dmg}')
    require(sha256_file(os_dmg) == OS_DMG_SHA256, 'OS image digest differs from the pinned IPSW member')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    image = out / 'owner-data.cdr'
    require(not image.exists(), f'Refuse to overwrite an existing Data seed: {image}')

    os_device = seed_device = None
    try:
        os_device, system_mount = attached_system_mount(os_dmg)
        launchd = system_mount / 'sbin/launchd'
        require(launchd.is_file() and sha256_file(launchd) == LAUNCHD_SHA256,
                'Require the unchanged supplied original OS mount')
        run(['hdiutil', 'create', '-size', f'{args.size_mib}m', '-layout', 'NONE', '-fs', 'APFS',
             '-volname', 'OwnerData', '-type', 'UDTO', image])
        mount = out / 'mount'
        mount.mkdir(exist_ok=True)
        attached = plistlib.loads(subprocess.check_output(
            ['hdiutil', 'attach', '-nobrowse', '-owners', 'off', '-mountpoint', mount, '-plist', image]))
        seed_device = attached['system-entities'][0]['dev-entry']
        volumes = [e for e in attached['system-entities'] if e.get('mount-point') == str(mount)]
        require(len(volumes) == 1, 'Require exactly one newly formatted scratch volume')
        created_uuid = plistlib.loads(subprocess.check_output(
            ['diskutil', 'info', '-plist', volumes[0]['dev-entry']]))['VolumeUUID']
        count, total = copy_var_tree(system_mount / 'private/var', mount)
    finally:
        if seed_device:
            subprocess.run(['hdiutil', 'detach', seed_device], check=False)
        if os_device:
            subprocess.run(['hdiutil', 'detach', os_device], check=False)

    replaced, normalized = patch_volume_uuid(image, created_uuid)

    # The APFS driver's own acceptance: the patched image must attach and
    # diskutil must report the pinned volume UUID.
    verify = plistlib.loads(subprocess.check_output(['hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', image]))
    verify_device = verify['system-entities'][0]['dev-entry']
    try:
        volumes = [e for e in verify['system-entities'] if 'mount-point' in e]
        require(len(volumes) == 1, 'Patched seed did not attach with exactly one volume')
        reported = plistlib.loads(subprocess.check_output(
            ['diskutil', 'info', '-plist', volumes[0]['dev-entry']]))['VolumeUUID']
        require(reported == TARGET_UUID, f'Patched seed reports VolumeUUID {reported}, not the pinned value')
    finally:
        subprocess.run(['hdiutil', 'detach', verify_device], check=False)

    data = image.read_bytes()
    require(len(data) == args.size_mib * 1024 ** 2 and data[32:36] == b'NXSB',
            'Host formatting did not produce the requested raw APFS container')
    report = dict(volume_uuid=TARGET_UUID, created_volume_uuid=created_uuid,
                  uuid_occurrences_replaced=replaced,
                  incompatible_features_normalized=normalized, bytes=len(data),
                  sha256=hashlib.sha256(data).hexdigest(),
                  source_regular_files=count, source_regular_bytes=total,
                  guest_mutable=True, initial_seed_signature_verified=False,
                  seed='Original private/var excluding staged_system_apps; symlinks preserved; '
                       'runtime directories added; volume UUID rewritten to the pinned scratch '
                       'UUID and the volume incompatible features rewritten from the formatter '
                       'case-insensitive-only declaration to the IPSW volumes normalization-'
                       'insensitive declaration in the same pass, with APFS object checksums '
                       'repaired and re-verified by attach')
    (out / 'seed.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
