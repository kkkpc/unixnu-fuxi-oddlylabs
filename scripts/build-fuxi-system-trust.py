#!/usr/bin/env python3
"""Build the fuxi payload's trust-cache bundle from the iPadOS 17.7.11 IPSW.

Shipped with the Build #42 payload change; the owner approved the push on 2026-11-05.

Why this exists: Build #41's payload carried NO trust cache at all
(payload.json trust_cache_sha256 is null; the CI `build payload` step passes
no --trust-cache), so AMFI had no CDHash for /sbin/launchd and the kernel
killed it with SIGKILL namespace 9 code 0x8 (EXEC_EXIT_REASON_SECURITY_POLICY).
The r3 ramdisk boot worked because it carried the RestoreTrustCache bundle;
the full-OS launchd is covered by a different module.

What it builds: upstream's own two-module original bundle, byte for byte:
  module 0 = StaticTrustCache  (covers launchd + dyld + kernelcache kexts;
              audit-target-userspace.py verifies launchd/dyld CDHashes
              against this module alone)
  module 1 = Cryptex1,SystemTrustCache (covers the 53 dyld-cache files;
              build-native-user-fixture.py asserts this coverage)
Both IPSW members are IM4P-wrapped version-2 modules already - unlike the
RestoreTrustCache, which was v1 and needed the r3 v1->v2 conversion, no
conversion is needed here. Every digest is pinned; any mismatch fails loudly
instead of producing a bundle the loader would refuse.

Pins (iPad7,1 / 17.7.11 / 21H461, j120ap, from UniXNU's
scripts/build-original-system-trust.py and the OS profile
profiles/os/ipados-17.7.11-21H461/profile.toml):
  static module sha256  da88460e6e513438d5307e5c526f76497a74754476a24da29f239f0c90120fc2
  system module sha256  d121ba89167e03aafd00fa687c30cd8ebc4ccafd10c1408adb2ba3de12403651
  bundle sha256         7416ca4f8377146626bb284e2133c76bee6cb4e3ee0af5d648b186235a7323a7
Layout is bundle-ipsw-trust.py's: u32 count, u32 offsets, modules in order
(static first - XNU's load_static_trust_cache treats module 0 as the static
trust cache and loads every module in the bundle; DarwinBoot's
ValidTrustCaches accepts up to 128 such modules).

Fetching reuses the fuxi line's established pattern (RangeFile over HTTP
range requests, as in scripts/build-fuxi-owner-root.py): only the manifest
and the two small trust-cache members are read, not the whole IPSW.

Usage (CI step, before `unixnu build payload`):
  python3 "$GITHUB_WORKSPACE/fuxi/scripts/build-fuxi-system-trust.py" \
      --out "$GITHUB_WORKSPACE/fuxi/build/system-trust/original-static-system.bundle"
Then the payload step gains:
  --trust-cache "$GITHUB_WORKSPACE/fuxi/build/system-trust/original-static-system.bundle"
and board.toml [payload] gains:
  trust_cache_sha256 = ["7416ca4f8377146626bb284e2133c76bee6cb4e3ee0af5d648b186235a7323a7"]
so payload.py's board allow-list accepts exactly this bundle.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import plistlib
import urllib.request
import zipfile

IPSW_URL = ('https://updates.cdn-apple.com/2025SpringFCS/fullrestores/122-77166/'
            'DCA6CFE8-90E9-4B92-880D-3DE171798E40/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw')
STATIC_SHA256 = 'da88460e6e513438d5307e5c526f76497a74754476a24da29f239f0c90120fc2'
SYSTEM_SHA256 = 'd121ba89167e03aafd00fa687c30cd8ebc4ccafd10c1408adb2ba3de12403651'
BUNDLE_SHA256 = '7416ca4f8377146626bb284e2133c76bee6cb4e3ee0af5d648b186235a7323a7'


class RangeFile(io.RawIOBase):
    """Seekable read-only view of a remote file over HTTP range requests (as in build-fuxi-owner-root.py)."""
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


def der(data, at):
    tag, size = data[at:at + 2]
    at += 2
    if size & 128:
        n = size & 127
        size = int.from_bytes(data[at:at + n], 'big')
        at += n
    if at + size > len(data):
        raise SystemExit('DER exceeds input')
    return tag, data[at:at + size], at + size


def unwrap_im4p(data, name):
    """Unwrap an IM4P file to its raw trust-cache module (same DER walk as bundle-ipsw-trust.py)."""
    tag, seq, end = der(data, 0)
    fields, at = [], 0
    while at < len(seq):
        kind, value, at = der(seq, at)
        fields.append((kind, value))
    if tag != 0x30 or end != len(data) or [k for k, _ in fields] != [0x16, 0x16, 0x16, 4] or fields[0][1] != b'IM4P':
        raise SystemExit(f'{name}: not an IM4P')
    return fields[3][1]


def require_module(data, expected_sha256, name):
    import struct
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SystemExit(f'{name}: module sha256 mismatch (not the pinned original)')
    version, = struct.unpack_from('<I', data)
    count, = struct.unpack_from('<I', data, 20)
    if version != 2 or len(data) != 24 + count * 24:
        raise SystemExit(f'{name}: not an exact version-2 trust module (version {version}, {len(data)} bytes)')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ipsw-url', default=IPSW_URL)
    args = parser.parse_args()
    with zipfile.ZipFile(RangeFile(args.ipsw_url)) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        identities = [i for i in manifest['BuildIdentities'] if i['Info']['DeviceClass'] == 'j120ap']
        if manifest['ProductBuildVersion'] != '21H461' or len(identities) != 2:
            raise SystemExit('Require the iPad7,1 17.7.11 (21H461) IPSW with both restore identities')
        modules = []
        for key, expected in (('StaticTrustCache', STATIC_SHA256),
                              ('Cryptex1,SystemTrustCache', SYSTEM_SHA256)):
            entry = identities[0]['Manifest'][key]
            original = archive.read(entry['Info']['Path'])
            if any(i['Manifest'][key]['Digest'] != hashlib.sha384(original).digest() for i in identities):
                raise SystemExit(f'{key}: manifest sha384 digest mismatch')
            module = unwrap_im4p(original, key)
            count = require_module(module, expected, key)
            print(f'{key}: {count} entries, {len(module)} bytes, sha256 {expected[:16]}... OK')
            modules.append(module)
    import struct
    bundle = struct.pack('<3I', 2, 12, 12 + len(modules[0])) + modules[0] + modules[1]
    digest = hashlib.sha256(bundle).hexdigest()
    if digest != BUNDLE_SHA256:
        raise SystemExit(f'bundle sha256 {digest} != pinned {BUNDLE_SHA256}')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(bundle)
    (args.out.with_suffix('.json')).write_text(json.dumps({
        'modules': ['StaticTrustCache', 'Cryptex1,SystemTrustCache'],
        'module_sha256': [STATIC_SHA256, SYSTEM_SHA256],
        'entries': [require_module(m, s, n) for m, s, n in
                    zip(modules, (STATIC_SHA256, SYSTEM_SHA256), ('static', 'system'))],
        'bundle_sha256': digest, 'modified': False}, indent=2) + '\n')
    print(f'{args.out}: {len(bundle)} bytes, bundle sha256 {digest} (pinned, OK)')


if __name__ == '__main__':
    main()
