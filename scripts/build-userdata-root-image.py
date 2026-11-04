#!/usr/bin/env python3
"""Build the images flashed to the fuxi `userdata` partition for the ShengUfs native
UFS root: the unchanged iPadOS OS and SystemOS disk images, byte for byte, behind a
small manifest. Fuxi port of UniXNU-sheng/scripts/build-userdata-root-image.py and
make-userdata-full.py, adapted to plain decoded image files on Linux (no hdiutil).

Layout (all offsets from the first byte of the image, which is the first byte of
`userdata`):

    0x000000  manifest block (4096 bytes, see below), then zero padding to 1 MiB
    0x100000  window "OS"        the whole OS disk image (GPT + APFS), 1 MiB aligned
    ....      window "SystemOS"  the whole SystemOS disk image, 1 MiB aligned

Manifest (little endian): "SHNGROOT", u32 version=1, u32 count, u64 image_bytes, then
`count` 128-byte entries {char name[32], u64 offset, u64 size, u32 block_size=512,
u32 flags(1=read-only), u8 sha256[32], 40 reserved bytes}, then at byte 4064 the
SHA-256 of bytes 0..4063. This is the layout ShengUfs RootLayout.h parses.

Geometry (4096-byte LBAs on LUN 0), verified 2026-11-04: userdata is the last GPT
partition (index 31) with first LBA 3110976 (0x2F7840), read from the official
HyperOS OS3.0.308.0.WMCCNXM fastboot ROM's gpt_main0.bin; the entry's last field is
the Qualcomm grow sentinel, so the span comes from the owner's unit itself:
fastboot getvar partition-size:userdata = 0x3804BBB sectors (2026-11-01), giving
last LBA 61850618 (0x3AFC3FA) and 240,637,591,552 partition bytes.

The window payloads are the decoded disk images of the iPadOS 17.7.11 IPSW
(21H461): OS member 044-76040-038.dmg decoded from its UDIF/LZFSE form, SystemOS
member 044-76034-038.dmg as shipped. Both are checked against the recorded
size and SHA-256 before anything is written.

Nothing is flashed here. Outputs (git-ignored build products):
  userdata-root.img        the dense root image (manifest + windows)
  userdata-root.json       report with the layout and hashes everything else pins to
  userdata-full.sparse     with --sparse-full: whole-partition Android sparse image
                           (windows + zero fill to the partition end), the file a
                           future, separately approved `fastboot flash userdata`
                           would use
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

MIB = 1024 * 1024
BLOCK = 4096
CHUNK = 8 * MIB

USERDATA_FIRST_LBA = 3110976          # 0x2F7840, official ROM GPT, partition index 31
USERDATA_LAST_LBA = 61850618          # 0x3AFC3FA, first + 0x3804BBB - 1 (unit getvar)
USERDATA_BYTES = (USERDATA_LAST_LBA - USERDATA_FIRST_LBA + 1) * 4096

# (window name, default input, recorded size, recorded sha256 of the decoded image)
WINDOWS = (
    ('OS', 'os.raw', 6077580800,
     'e5634d04a8ac35f024845f583394e0a35deb26a04cb0c00286a8674e25a9a4f2'),
    ('SystemOS', 'systemos.raw', 3303014400,
     'b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f'),
)
DEFAULT_INPUTS = Path.home() / 'workspace/unixnu-fuxi/fullos-inputs'
DEFAULT_OUT = Path(__file__).resolve().parents[1] / 'build/userdata-root'


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def align(value, unit=MIB):
    return (value + unit - 1) // unit * unit


def layout(sizes):
    entries, cursor = [], MIB
    for name, size in sizes:
        entries.append((name, cursor, size))
        cursor += align(size)
    return entries, cursor


def manifest(entries, image_bytes, digests):
    header = bytearray(4096)
    header[0:8] = b'SHNGROOT'
    struct.pack_into('<IIQ', header, 8, 1, len(entries), image_bytes)
    for index, (name, offset, size) in enumerate(entries):
        struct.pack_into('<32sQQII32s40s', header, 24 + 128 * index,
                         name.encode(), offset, size, 512, 1, digests[name], bytes(40))
    header[4064:4096] = hashlib.sha256(bytes(header[:4064])).digest()
    return bytes(header)


def build_root_image(inputs, output):
    sizes = []
    for (name, _fname, size, digest) in WINDOWS:
        path = inputs[name]
        if path.stat().st_size != size:
            raise SystemExit(f'Refusing: {path} is {path.stat().st_size} bytes, recorded {size}')
        got = sha256_file(path)
        if got != digest:
            raise SystemExit(f'Refusing: {path} sha256 {got} differs from the recorded {digest}')
        print(f'{name}: source {path.name} sha256 matches the recorded extraction')
        sizes.append((name, size))
    entries, image_bytes = layout(sizes)
    print(f'image {image_bytes} bytes ({image_bytes / 2**30:.2f} GiB); userdata holds {USERDATA_BYTES} bytes')
    if image_bytes > USERDATA_BYTES:
        raise SystemExit('Refusing: the image is larger than the userdata partition')
    digests = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'wb') as out:
        out.truncate(image_bytes)
        for (name, offset, size), (wname, _f, _s, _d) in zip(entries, WINDOWS):
            assert name == wname
            digest = hashlib.sha256()
            out.seek(offset)
            done = 0
            with open(inputs[name], 'rb', buffering=0) as handle:
                while done < size:
                    data = handle.read(min(CHUNK, size - done))
                    if not data:
                        raise SystemExit(f'Short read from {inputs[name]} at {done}')
                    digest.update(data)
                    out.write(data)
                    done += len(data)
            digests[name] = digest.digest()
            print(f'{name}: {size} bytes at {offset:#x} sha256 {digest.hexdigest()}')
        out.seek(0)
        out.write(manifest(entries, image_bytes, digests))
    report = {'image': output.name, 'image_bytes': image_bytes,
              'image_sha256': sha256_file(output),
              'manifest_sha256': hashlib.sha256(manifest(entries, image_bytes, digests)).hexdigest(),
              'windows': [{'name': n, 'offset': o, 'size': s, 'sha256': digests[n].hex()}
                          for n, o, s in entries],
              'userdata_first_lba': USERDATA_FIRST_LBA, 'userdata_last_lba': USERDATA_LAST_LBA,
              'userdata_bytes': USERDATA_BYTES,
              'flash_command': f'fastboot flash userdata <sparse image from --sparse-full>'}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return report


def verify_root_image(image_path):
    """Parse an image back under the RootLayout.h rules and re-hash its windows."""
    with open(image_path, 'rb') as handle:
        head = handle.read(4096)
        if head[0:8] != b'SHNGROOT':
            raise SystemExit('verify: no SHNGROOT magic')
        version, count, image_bytes = struct.unpack_from('<IIQ', head, 8)
        if version != 1 or not (1 <= count <= 4):
            raise SystemExit(f'verify: version {version} count {count}')
        if hashlib.sha256(head[:4064]).digest() != head[4064:4096]:
            raise SystemExit('verify: manifest self-hash mismatch')
        if image_bytes < 4096 or image_bytes & 4095 or image_bytes > USERDATA_BYTES:
            raise SystemExit(f'verify: image_bytes {image_bytes} out of bounds')
        seen = []
        for index in range(count):
            name, offset, size, block_size, flags, sha = struct.unpack_from(
                '<32sQQII32s', head, 24 + 128 * index)
            name = name.split(b'\0')[0].decode()
            if (offset & 4095) or offset < 4096 or (size & 511) or not size \
                    or size > image_bytes - offset or block_size != 512 or flags != 1:
                raise SystemExit(f'verify: window {name} fails the parser bounds')
            for other_off, other_size in seen:
                if offset < other_off + align(other_size, 4096) and other_off < offset + align(size, 4096):
                    raise SystemExit(f'verify: window {name} overlaps another window')
            seen.append((offset, size))
            digest = hashlib.sha256()
            handle.seek(offset)
            done = 0
            while done < size:
                data = handle.read(min(CHUNK, size - done))
                if not data:
                    raise SystemExit(f'verify: short read in window {name}')
                digest.update(data)
                done += len(data)
            status = 'OK' if digest.digest() == sha else 'MISMATCH'
            print(f'verify: window {name} at {offset:#x} size {size} sha256 {status}')
            if status != 'OK':
                raise SystemExit(f'verify: window {name} hash mismatch')
    print(f'verify: manifest self-hash OK; image_bytes {image_bytes}; parser bounds OK')
    return True


class SparseWriter:
    """Android sparse image writer, ported from UniXNU-sheng make-userdata-full.py."""

    RAW, FILL = 0xCAC1, 0xCAC2
    MAX_RAW = 4096
    ZERO = bytes(BLOCK)

    def __init__(self, path, total_blocks):
        self.out = open(path, 'wb')
        self.out.write(bytes(28))
        self.total, self.chunks, self.blocks = total_blocks, 0, 0
        self.raw, self.raw_blocks, self.zero_run = bytearray(), 0, 0

    def flush_raw(self):
        if self.raw_blocks:
            self.out.write(struct.pack('<HHII', self.RAW, 0, self.raw_blocks,
                                        12 + len(self.raw)) + self.raw)
            self.chunks += 1
            self.raw, self.raw_blocks = bytearray(), 0

    def flush_zero(self):
        if self.zero_run:
            self.out.write(struct.pack('<HHII', self.FILL, 0, self.zero_run, 16) + bytes(4))
            self.chunks += 1
            self.zero_run = 0

    def data(self, buffer):
        assert len(buffer) % BLOCK == 0
        for at in range(0, len(buffer), BLOCK):
            block = buffer[at:at + BLOCK]
            if block == self.ZERO:
                self.flush_raw()
                self.zero_run += 1
            else:
                self.flush_zero()
                self.raw += block
                self.raw_blocks += 1
                if self.raw_blocks == self.MAX_RAW:
                    self.flush_raw()
        self.blocks += len(buffer) // BLOCK

    def zeros(self, count):
        self.flush_raw()
        self.zero_run += count
        self.blocks += count

    def close(self):
        self.flush_raw()
        self.flush_zero()
        assert self.blocks == self.total, (self.blocks, self.total)
        self.out.seek(0)
        self.out.write(struct.pack('<IHHHHIIII', 0xED26FF3A, 1, 0, 28, 12, BLOCK,
                                    self.total, self.chunks, 0))
        self.out.close()


def build_sparse(root_image, report, output):
    """Stream the whole-partition sparse image from the verified dense root image."""
    entries = [(w['name'], w['offset'], w['size']) for w in report['windows']]
    image_bytes = report['image_bytes']
    writer = SparseWriter(output, USERDATA_BYTES // BLOCK)
    with open(root_image, 'rb', buffering=0) as handle:
        done = 0
        while done < image_bytes:
            data = handle.read(min(CHUNK, image_bytes - done))
            if len(data) % BLOCK:
                data += bytes(BLOCK - len(data) % BLOCK)
            writer.data(data)
            done += len(data)
    writer.zeros((USERDATA_BYTES - image_bytes) // BLOCK)
    writer.close()
    print(f'{output}: partition {USERDATA_BYTES} bytes, root image {image_bytes} bytes, '
          f'manifest {report["manifest_sha256"]} (from verified report)')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--os', type=Path, default=DEFAULT_INPUTS / 'os.raw')
    parser.add_argument('--systemos', type=Path, default=DEFAULT_INPUTS / 'systemos.raw')
    parser.add_argument('--out-dir', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--sparse-full', action='store_true',
                        help='also stream the whole-partition Android sparse image')
    parser.add_argument('--verify', type=Path, metavar='IMAGE',
                        help='only parse an existing root image back and re-hash its windows')
    args = parser.parse_args()
    if args.verify:
        verify_root_image(args.verify)
        return
    inputs = {'OS': args.os, 'SystemOS': args.systemos}
    root_image = args.out_dir / 'userdata-root.img'
    report = build_root_image(inputs, root_image)
    verify_root_image(root_image)
    if args.sparse_full:
        build_sparse(root_image, report, args.out_dir / 'userdata-full.sparse')


if __name__ == '__main__':
    main()
