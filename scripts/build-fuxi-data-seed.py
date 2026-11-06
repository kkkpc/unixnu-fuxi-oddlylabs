#!/usr/bin/env python3
"""Build this board's scratch Data seed (macOS runner only).

The workflow runs this script in its own job on a macOS 14 runner, NOT in
the macos-26 image job: the volume must be formatted by that generation's
newfs_apfs (2142, the generation that formatted this IPSW's own volumes -
see the formatter note below). The image job downloads the finished seed
as a workflow artifact. Run locally on a Mac it works the same; pass
--os-dmg with an extracted OS image, or --from-ipsw to range-extract the
pinned OS member from the IPSW first (the RangeFile reader is
build-fuxi-owner-root.py's, kept in sync by hand).

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
A case-insensitive formatter declares APFS_INCOMPAT_CASE_INSENSITIVE (0x1),
alone (the macOS 26 formatter) or paired with NORMALIZATION_INSENSITIVE
(0x9 in total); both IPSW volumes of this OS declare 0x8 without 0x1
(SystemOS 0x28, System 0x8). The chain47 device boot (2026-11-06) hung
with a permanently black screen inside the scratch Data mount's
synchronous APFS mount() call - the only no-timeout call in the Data path
(the seed lookup, the boot-manifest publish and every glue failure were
audited to fail loudly onto a panic page, and the sibling chain46 image
booted normally on the same unit minutes later) - so the seed declares
0x8 exactly like the volumes this kernel mounts. The patch accepts only
a formatter declaration (0x1, 0x9, or an already-conforming 0x8) and
refuses anything else instead of guessing.

The feature word was not the hang, though: chain48, carrying the 0x8
seed, hung black in exactly the same way, exonerating it. The remaining
seed-only delta is the formatter generation itself - the macOS 26 seed
was written by newfs_apfs 2811 (2025) while the mounting APFS is iOS
17.7's (2142 generation), and the trigger is expected in the structures
below the superblock (omap/btree/spaceman) that the newer formatter
writes. That is why the workflow's seed job runs on macOS 14, whose
newfs_apfs is the IPSW volumes' own 2142 generation.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import urllib.request
import uuid
import zipfile

OS_DMG_SHA256 = '3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d'
OS_DMG_NAME = '044-76040-038.dmg'
# The same pinned IPSW build-fuxi-owner-root.py extracts from; keep in sync.
IPSW_URL = ('https://updates.cdn-apple.com/2025SpringFCS/fullrestores/122-77166/'
            'DCA6CFE8-90E9-4B92-880D-3DE171798E40/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw')
OS_UUID = '04769D26-2CA0-4825-B443-E2E5F88300F2'
LAUNCHD_SHA256 = '8cec9a3c44a443b08e977ccc5d577850316ad428c575dc01f09b018dbd5b6a25'
TARGET_UUID = '18AB5557-DC2D-469B-8758-855E60F5B0DF'
BLOCK = 4096
OBJECT_TYPE_APFS = 0x000D  # volume superblock
FLETCHER_MOD = (1 << 32) - 1
APSB_INCOMPAT_OFFSET = 56  # apfs_incompatible_features in the volume superblock
# APFS_INCOMPAT_CASE_INSENSITIVE (0x1), alone as the macOS 26 formatter writes
# it or paired with NORMALIZATION_INSENSITIVE (0x9) as the macOS 14 one may.
SEED_INCOMPAT_FORMATTERS = (0x1, 0x9)
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


# --- IPSW member extraction (for --from-ipsw) --------------------------------
# The RangeFile reader is build-fuxi-owner-root.py's, duplicated because that
# script runs its pipeline at import time; keep the two copies in sync.

class RangeFile(io.RawIOBase):
    """A seekable read-only view of a remote file over HTTP range requests."""

    BLOCK = 8 * 1024 * 1024

    def __init__(self, url):
        self.url = url
        request = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(request) as response:
            self.size = int(response.headers['Content-Length'])
        self.position = 0
        self.cache = {}

    def seekable(self):
        return True

    def seek(self, offset, whence=io.SEEK_SET):
        self.position = {io.SEEK_SET: offset, io.SEEK_CUR: self.position + offset,
                         io.SEEK_END: self.size + offset}[whence]
        return self.position

    def tell(self):
        return self.position

    def readinto(self, buffer):
        if self.position >= self.size:
            return 0
        block_index, offset = divmod(self.position, self.BLOCK)
        if block_index not in self.cache:
            if len(self.cache) > 4:
                self.cache.clear()
            start = block_index * self.BLOCK
            request = urllib.request.Request(self.url, headers={'Range': f'bytes={start}-{start + self.BLOCK - 1}'})
            with urllib.request.urlopen(request) as response:
                self.cache[block_index] = response.read()
        block = self.cache[block_index]
        take = min(len(buffer), len(block) - offset, self.size - self.position)
        buffer[:take] = block[offset:offset + take]
        self.position += take
        return take


def extract_os_dmg(destination):
    """Range-extract the pinned OS member of the IPSW to destination."""
    if destination.is_file() and sha256_file(destination) == OS_DMG_SHA256:
        return destination
    print(f'extracting {destination.name} from the IPSW (range requests)', flush=True)
    with zipfile.ZipFile(RangeFile(IPSW_URL)) as archive:
        member = next(name for name in archive.namelist() if Path(name).name == OS_DMG_NAME)
        with archive.open(member) as source, destination.open('wb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
    require(sha256_file(destination) == OS_DMG_SHA256,
            f'{destination.name} digest differs from the pinned IPSW member after extraction')
    return destination


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
    superblock's incompatible-feature word from the formatter's declaration
    to SEED_INCOMPAT_TARGET (see the module docstring). Returns (UUID
    occurrences replaced, superblocks normalized, sorted list of the
    distinct incompatible values the formatter had written).
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
    observed = set()
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
        require(incompat == SEED_INCOMPAT_TARGET or incompat in SEED_INCOMPAT_FORMATTERS,
                f'Volume superblock block {block_index} declares incompatible features '
                f'0x{incompat:x}, not a formatter declaration; refusing to patch')
        observed.add(incompat)
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
    return len(occurrences), len(touched), sorted(observed)


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
    parser.add_argument('--os-dmg', type=Path,
                        help='the extracted OS container image (044-76040-038.dmg) from the kernel build cache')
    parser.add_argument('--from-ipsw', action='store_true',
                        help='range-extract the OS image from the pinned IPSW instead of --os-dmg')
    parser.add_argument('--out', type=Path, default=Path('build/data-seed'))
    parser.add_argument('--size-mib', type=int, default=256)
    args = parser.parse_args()
    require(sys.platform == 'darwin', 'The Data seed is built with hdiutil: macOS only')
    require(bool(args.os_dmg) != args.from_ipsw, 'Pass exactly one of --os-dmg and --from-ipsw')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.from_ipsw:
        os_dmg = extract_os_dmg(out / OS_DMG_NAME)
    else:
        os_dmg = args.os_dmg.resolve()
        require(os_dmg.is_file(), f'OS image not found: {os_dmg}')
    require(sha256_file(os_dmg) == OS_DMG_SHA256, 'OS image digest differs from the pinned IPSW member')
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

    replaced, normalized, incompat_from = patch_volume_uuid(image, created_uuid)

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
                  incompatible_features_normalized=normalized,
                  incompatible_features_from=[f'0x{value:x}' for value in incompat_from],
                  bytes=len(data),
                  sha256=hashlib.sha256(data).hexdigest(),
                  source_regular_files=count, source_regular_bytes=total,
                  guest_mutable=True, initial_seed_signature_verified=False,
                  seed='Original private/var excluding staged_system_apps; symlinks preserved; '
                       'runtime directories added; volume UUID rewritten to the pinned scratch '
                       'UUID and the volume incompatible features rewritten from the formatter '
                       'case-insensitive declaration to the IPSW volumes normalization-'
                       'insensitive declaration in the same pass, with APFS object checksums '
                       'repaired and re-verified by attach')
    (out / 'seed.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
