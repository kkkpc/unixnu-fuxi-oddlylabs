#!/usr/bin/env python3
"""Generate this board's owner-root policies and the probe bundle archive, in-tree.

This runs first in the board's kernel archive order (see board.toml), on the macOS
build host, before any compiling: a policy failure stops the build here instead of
at the kernel link. CONFIG_XNU_VERIFIED_ROOT_PROBE makes build-xnu-4k-baseline.sh
force-load build/verified-root-os-xnu-bundle/libVerifiedRootProbe.a; that archive
carries both the signed per-volume policies (verified_root_policies /
verified_root_key, which the UFS driver verifies every root read against) and the
VerifiedRoot kit's vr_* implementation the driver calls, and
scripts/build-verified-root-probe.py is its only builder.

The pipeline is UniXNU's own, frozen to the IPSW payload rather than to any board:
the expected volume UUIDs and image digests in its scripts are this iPadOS
17.7.11 image's own constants. The two volume images are extracted from the IPSW
over HTTP range requests into the firmware cache the UniXNU scripts read (only
the members this pipeline needs; both digests are asserted against their pins).
The OS policy is signed by UniXNU's scripts/build-owner-os-policy.py itself,
over the OS volume attached read-only with hdiutil exactly as that script
requires (it re-validates the attachment, the whole-disk size and the volume
UUID before signing). The SystemOS policy is made with
kits/VerifiedRoot/tools/manifest.py directly over the raw SystemOS image (the
044-76034-038.dmg member is the raw APFS volume image), with the OS script's
verification steps mirrored so the probe builder finds the same
verification.json shape for both volumes. The host verification library is
compiled the way kits/VerifiedRoot/tests/check.py builds it, against the
Homebrew openssl@3 the image job installs.

The owner keypair (RSA-3072, exponent 65537, as manifest.py's public_anchor
requires) is generated fresh into build/verified-root-host/ on every build: the
policies, the bundle and the trusted key embedded in the kernel are all produced
and consumed within the same build, so no key material persists or is
committed, and the policies are the full form (signed header plus the complete
hash table), so the kernel carries the tables and the flashed root image stays
the version-1 two-window layout UniXNU-sheng's later header-only form would
need ".vroot" objects in a version-2 root image to replace.
"""
import ctypes
import hashlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]   # the assembled build tree: scripts are copied into it
TARGETS = ROOT / '.cache/firmware/target-volumes'
OS_DMG = TARGETS / '044-76040-038.dmg'
SYSTEMOS_DMG = TARGETS / '044-76034-038.dmg'
OS_DMG_SHA256 = '3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d'
SYSTEMOS_IMAGE_SHA256 = 'b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f'
OS_UUID = '04769D26-2CA0-4825-B443-E2E5F88300F2'
SYSTEMOS_UUID = '8846FE78-2910-4297-AF97-D59BB6F8FC16'
SYSTEMOS_BYTES = 3303014400
IPSW_URL = ('https://updates.cdn-apple.com/2025SpringFCS/fullrestores/122-77166/'
            'DCA6CFE8-90E9-4B92-880D-3DE171798E40/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw')
HOST = ROOT / 'build/verified-root-host'
KEYS = HOST / 'keys'
BUNDLE = ROOT / 'build/verified-root-os-xnu-bundle/libVerifiedRootProbe.a'

# Every CDN request is bounded: a stalled connection must fail loudly, never
# wait forever. Build #98 (2026-11-08) sat in this archive for 2h50m because
# the urlopen calls below carried no timeout at all, and the extraction
# print was block-buffered away, so the step showed no output at all.
HTTP_TIMEOUT = 30
HTTP_RETRIES = 3


def _retryable(error):
    """Only recoverable network errors are retried; an HTTP 4xx other than
    408/429 is a definitive answer and fails at once."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (408, 429) or error.code >= 500
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError,
                              http.client.HTTPException))


def _bounded(kind, request, consume):
    """Run one CDN request under the retry bound and return consume(response).

    The response is consumed inside the bound, so a transfer that stalls
    mid-body is retried as a whole rather than waited on. The final failure
    is logged with its URL, request kind and exception, then re-raised: the
    build exits non-zero instead of hanging."""
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                return consume(response)
        except Exception as error:
            if attempt >= HTTP_RETRIES or not _retryable(error):
                print(f'CDN {kind} request failed after {attempt} attempt(s): '
                      f'{request.full_url}: {error!r}', flush=True)
                raise
            wait = 2 * attempt
            print(f'CDN {kind} request attempt {attempt} failed: {error!r}; '
                  f'retrying in {wait}s', flush=True)
            time.sleep(wait)


def run(command, **kwargs):
    print('+', ' '.join(str(v) for v in command), flush=True)
    return subprocess.run([str(v) for v in command], check=True, **kwargs)


def require(value, message):
    if not value:
        raise SystemExit(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


class RangeFile(io.RawIOBase):
    """A seekable read-only view of a remote file over HTTP range requests."""

    BLOCK = 8 * 1024 * 1024

    def __init__(self, url):
        self.url = url
        request = urllib.request.Request(url, method='HEAD')
        self.size = _bounded('HEAD', request,
                             lambda response: int(response.headers['Content-Length']))
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
            self.cache[block_index] = _bounded('Range GET', request,
                                               lambda response: response.read())
        block = self.cache[block_index]
        take = min(len(buffer), len(block) - offset, self.size - self.position)
        buffer[:take] = block[offset:offset + take]
        self.position += take
        return take


# --- Extract the two volume images the pipeline reads ------------------------
TARGETS.mkdir(parents=True, exist_ok=True)
for path, expected in ((OS_DMG, OS_DMG_SHA256), (SYSTEMOS_DMG, SYSTEMOS_IMAGE_SHA256)):
    if path.is_file() and sha256(path) == expected:
        continue
    print(f'extracting {path.name} from the IPSW (range requests)', flush=True)
    with zipfile.ZipFile(RangeFile(IPSW_URL)) as archive:
        member = next(name for name in archive.namelist() if Path(name).name == path.name)
        with archive.open(member) as source, path.open('wb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
    require(sha256(path) == expected, f'{path.name} digest differs from its pin after extraction')

# --- Host kit: owner keypair + the C verification library --------------------
KEYS.mkdir(parents=True, exist_ok=True)
if not (KEYS / 'owner.pem').is_file():
    run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072',
         '-pkeyopt', 'rsa_keygen_pubexp:65537', '-out', KEYS / 'owner.pem'])
    run(['openssl', 'pkey', '-in', KEYS / 'owner.pem', '-pubout', '-out', KEYS / 'owner-public.pem'])
prefix = Path(subprocess.check_output(['brew', '--prefix', 'openssl@3'], text=True).strip())
library = HOST / 'verified-root.dylib'
run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-dynamiclib',
     '-I', ROOT / 'kits/VerifiedRoot/include', '-I', prefix / 'include',
     ROOT / 'kits/VerifiedRoot/src/verified_root.c', ROOT / 'kits/VerifiedRoot/tests/openssl_provider.c',
     '-L', prefix / 'lib', '-lcrypto', '-o', library])

# --- OS policy: attach read-only, then UniXNU's own policy script ------------
# build-owner-os-policy.py expects the OS (System) volume mounted at
# .cache/firmware/target-volumes/os-mount and re-validates the attachment itself
# (whole-disk size, volume UUID, read-only) before signing anything. The dmg
# carries a whole APFS container, so attach it plainly, find the mounted volume
# whose diskutil VolumeUUID is the System volume's, and point os-mount at it.
mount = TARGETS / 'os-mount'
whole_device = None
try:
    run(['hdiutil', 'attach', '-readonly', '-nobrowse', OS_DMG])
    info = plistlib.loads(subprocess.check_output(['hdiutil', 'info', '-plist']))
    entities = next(framework['system-entities'] for framework in info['images']
                    if framework.get('image-path') == str(OS_DMG))
    whole_device = next((e['dev-entry'] for e in entities if e.get('content-hint') == 'GUID_partition_scheme'), None)
    system_mount = None
    for entity in entities:
        if 'mount-point' not in entity:
            continue
        volume = plistlib.loads(subprocess.check_output(
            ['diskutil', 'info', '-plist', entity['mount-point']]))
        if volume.get('VolumeUUID') == OS_UUID:
            system_mount = entity['mount-point']
            break
    require(system_mount, 'Attached OS image has no mounted volume with the System volume UUID')
    if mount.is_symlink() or mount.is_file():
        mount.unlink()
    elif mount.is_dir():
        mount.rmdir()
    mount.symlink_to(system_mount)
    run([sys.executable, ROOT / 'scripts/build-owner-os-policy.py'], cwd=ROOT)
finally:
    if mount.is_symlink():
        mount.unlink()
    if whole_device:
        subprocess.run(['hdiutil', 'detach', whole_device], check=False)

# --- SystemOS policy: manifest.make over the raw image + C verification ------
spec = importlib.util.spec_from_file_location('verified_manifest', ROOT / 'kits/VerifiedRoot/tools/manifest.py')
manifest_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest_module)
out = ROOT / 'build/verified-root-systemos'
with SYSTEMOS_DMG.open('rb', buffering=1024 * 1024) as stream:
    record = manifest_module.make(stream, SYSTEMOS_BYTES, KEYS / 'owner.pem', KEYS / 'owner-public.pem',
                                  SYSTEMOS_UUID, 1, out)
require(record['image_sha256'] == SYSTEMOS_IMAGE_SHA256, 'SystemOS policy image digest mismatch')


class View(ctypes.Structure):
    _fields_ = [('hashes', ctypes.c_void_p), ('image_bytes', ctypes.c_uint64), ('block_count', ctypes.c_uint64),
                ('generation', ctypes.c_uint64), ('volume_uuid', ctypes.c_uint8 * 16), ('image_sha256', ctypes.c_uint8 * 32)]


native = ctypes.CDLL(str(library))
native.vr_host_open.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(View)]
native.vr_host_block.argtypes = [ctypes.POINTER(View), ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t]
encoded = ctypes.create_string_buffer((out / 'manifest.bin').read_bytes())
anchor = ctypes.create_string_buffer((out / 'trusted-key.bin').read_bytes())
view = View()
if native.vr_host_open(encoded, len(encoded) - 1, anchor, 1, ctypes.byref(view)) or \
        bytes(view.volume_uuid) != uuid.UUID(SYSTEMOS_UUID).bytes:
    raise SystemExit('SystemOS: real C signature/volume authentication failed')
complete = hashlib.sha256()
indices = [0, 1, view.block_count // 2, view.block_count - 1]
samples, lengths = [], []
with SYSTEMOS_DMG.open('rb', buffering=1024 * 1024) as stream:
    for index in range(view.block_count):
        block = stream.read(min(4096, view.image_bytes - index * 4096))
        if native.vr_host_block(ctypes.byref(view), index, block, len(block)) != 0:
            raise SystemExit(f'SystemOS: actual C block verification failed at {index}')
        complete.update(block)
        if index in indices:
            samples.append(block.ljust(4096, b'\0'))
            lengths.append(len(block))
    if stream.read(1):
        raise SystemExit('SystemOS image exceeded its authenticated exact bounds')
if complete.digest() != bytes(view.image_sha256) or complete.hexdigest() != record['image_sha256']:
    raise SystemExit('SystemOS: actual complete image digest differs')
(out / 'original-samples.bin').write_bytes(b''.join(samples))
report = dict(image_bytes=int(view.image_bytes), blocks_verified=int(view.block_count),
              image_sha256=complete.hexdigest(), volume_uuid=SYSTEMOS_UUID,
              generation=int(view.generation), source_compressed_sha256=SYSTEMOS_IMAGE_SHA256,
              source_format='raw APFS volume image', host_bus_protocol='file',
              host_media_writable=False, trusted_key_sha256=record['trusted_key_sha256'],
              actual_sample_indices=indices, actual_sample_lengths=lengths,
              real_c_signature_and_block_verification=True, original_image_modified=False,
              host_only=True, boot_root_authenticated=False, qemu_tested=False, hardware_tested=False)
(out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(f'PASS: SystemOS signature and every {view.block_count} block verified by real C/RSA', flush=True)

# --- Bundle: UniXNU's probe builder re-verifies and compiles both ------------
# The probe builder replays the bsd_init compile record, whose -I list names the
# header-export staging directories under build/xnu/ios-obj/EXPORT_HDRS. The
# bootstrap pass that leaves the record stops at its link, before the export
# phase creates all of them (Build #35: EXPORT_HDRS/libsa missing, and clang's
# -Werror turns the missing include directory into an error even though none of
# the probe sources include anything from it). Create the ones the record names
# that do not exist yet; a header a source genuinely needs would still fail
# loudly as file-not-found. The kernel build creates the obj/ variant of the
# libsa staging directory itself (build-xnu-4k-baseline.sh, its mkdir line).
record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/bsd/DEVELOPMENT/'
                     'bsd_init.o.json').read_text().strip().rstrip(','))
arguments = record['arguments']
for index, value in enumerate(arguments):
    include = value[2:] if value.startswith('-I') and len(value) > 2 else \
        arguments[index + 1] if value == '-I' and index + 1 < len(arguments) else None
    if include and Path(include).is_absolute() and str(Path(include)).startswith(str(ROOT)) \
            and not Path(include).exists():
        Path(include).mkdir(parents=True, exist_ok=True)
        print(f'created header-export staging directory the bootstrap did not reach: {include}', flush=True)
run([sys.executable, ROOT / 'scripts/build-verified-root-probe.py',
     '--component', 'os', '--include-systemos'], cwd=ROOT)
require(BUNDLE.is_file(), f'Probe bundle archive missing after its builder ran: {BUNDLE}')
require((ROOT / 'build/verified-root-os/verification.json').is_file(), 'OS policy verification report missing')
print(f'PASS: owner-root policies signed and bundle compiled: {BUNDLE.relative_to(ROOT)}', flush=True)
