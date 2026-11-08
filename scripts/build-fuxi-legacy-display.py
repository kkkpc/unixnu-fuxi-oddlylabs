#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Build build/native-legacy-display/libNativeLegacyDisplay.late.a for fuxi.

Binds the fixed GopFramebuffer component's NativeLegacyDisplay (the
owned concrete backend) to the unchanged original IOMobileFramebufferLegacy
lifecycle of iPadOS 17.7.11 (21H461), for the CPU-first display route.

Every original address comes from fuxi's own E2 ABI record
(scripts/fuxi-21H461-mobile-graphics-legacy-abi.json, sha256 pinned
below); nothing is taken from another board's builder or bindings.
The record's provenance limits are inherited, not upgraded: its
runtime-metadata leg was substituted under the audit's own fallback
rule, the instance size is a carried value, and
original_client_initializer is not qualified and must never appear
in the generated bindings.

Build-time identity gates, all hard failures:
  * the record file's sha256 equals the pinned E2 record hash;
  * a verification original is located uniquely in the actual build
    tree (a staged prelink candidate if one exists, else the
    decompressed original kernelcache, itself verified against the
    OS profile's kernelcache pin; the kernelcache normally appears
    only at prelink time, after the archive steps, so the builder
    materializes it through the framework's own CLI when absent),
    and its IOMobileGraphicsFamily __TEXT_EXEC hashes to the
    record's family_text_sha256;
  * the compiled component object's vtable matches the record
    (owned entries are the component's own methods or guarded
    abstract leaves; original-class entries resolve to bindings at
    the record's addresses), and the object's undefined
    original/binding imports are exactly the binding set. Bindings
    come from the record's bindings map plus derivations from the
    record's own method table in the accounted forms implemented
    below (the slot-21 init alias, exact opaque slot names,
    compiler-verified named methods at cross-checked slots, and
    qualified base calls matched to the component's override twin
    at the same slot); anything else refuses, and Gate 3 prints the
    complete violation list before failing.

The archive contains exactly three members: the late-ified component
object, the generated original-bindings object, and the board glue
(package/FuxiLegacyDisplayProbe.cpp). No presenter, no other
subsystem objects.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

from kernel_target import ARCH, IOS_VERSION, TRIPLE

if ARCH != 'arm64' or IOS_VERSION.split('.')[0] != '17':
    raise SystemExit('The fuxi legacy display builder only supports arm64 iOS 17. '
                     'The E2 ABI record is qualified for 21H461 only.')

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/native-legacy-display'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'kits/XnuPrelink'))
from native_prelink import macho, backed_offset, exports, unserialize_xml  # noqa: E402

RECORD = ROOT / 'scripts/fuxi-21H461-mobile-graphics-legacy-abi.json'
RECORD_SHA256 = 'f5d3f629a7cc507c493c9ccb05de2cf610110afa8a133c0cb06e213a7ecec229'
KERNELCACHE_SHA256 = 'f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7'
FAMILY_ID = 'com.apple.iokit.IOMobileGraphicsFamily'
# Slots the component itself overrides with concrete behaviour; the
# remaining abstract slots are guarded leaves. Determined by the
# component source at the pinned revision, cross-checked below
# against the compiled vtable.
OWNED_CONCRETE = (0, 1, 7, 14, 84, 86, 87, 141, 155, 184, 188, 288, 290, 296, 301)


def run(cmd, **kw):
    return subprocess.check_output([str(x) for x in cmd], timeout=180, **kw)


def require(value, why):
    if not value:
        raise SystemExit(why)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def family_text_sha256(blob):
    """Hash the IOMobileGraphicsFamily __TEXT_EXEC of a prelinked-format
    Mach-O (staged candidate or decompressed kernelcache), located via
    its own __PRELINK_INFO. Mirrors the E2 audit's extraction."""
    image = macho(blob)

    def read(va, n):
        at = backed_offset(image['segments'], va, n, len(blob))
        return blob[at:at + n]

    info = next(s for s in image['segments'] if s['name'] == '__PRELINK_INFO')
    at = backed_offset(image['segments'], info['va'], info['filesize'], len(blob))
    meta = unserialize_xml(blob[at:at + info['filesize']])
    entries = {e['CFBundleIdentifier']: e for e in meta['_PrelinkInfoDictionary']}
    require(FAMILY_ID in entries, 'verification original has no IOMobileGraphicsFamily module')
    entry = entries[FAMILY_ID]
    hdr = backed_offset(image['segments'], entry['_PrelinkExecutableLoadAddr'], 32, len(blob))
    module = macho(blob, hdr)
    ftext = next(s for s in module['segments'] if s['name'] == '__TEXT_EXEC')
    return hashlib.sha256(read(ftext['va'], ftext['size'])).hexdigest(), ftext


# --- Gate 1: the E2 record itself -------------------------------------------
require(RECORD.is_file(), f'E2 ABI record missing: {RECORD}')
require(sha(RECORD) == RECORD_SHA256,
        'E2 ABI record sha256 does not match the pinned f5d3f629 record; refusing to build')
audit = json.loads(RECORD.read_text())
methods = audit['methods']
pure = audit['abstract_slots']
require(len(methods) == 358, 'E2 record does not carry the 358-entry method table')
require(int(audit['bindings']['__ZTV25IOMobileFramebufferLegacy'], 16) == int(audit['legacy_vptr'], 16) - 16,
        'E2 record vtable binding is inconsistent with its legacy_vptr')
instance_match = re.match(r'(\d+)', str(audit['legacy_instance_bytes']))
require(instance_match and int(instance_match.group(1)) == 0x18a0,
        'E2 record instance size is not the carried 0x18a0 value')
bindings = {name: int(value, 16) for name, value in audit['bindings'].items()
            if isinstance(value, str) and value.startswith('0x')}
require('original_client_initializer' not in json.dumps(bindings),
        'unqualified original_client_initializer leaked into the binding set')

# The E2 record carries the original class's init address in its top-level
# original_init field (and again in methods[21]) but not in bindings: the
# audit qualified init as a standalone field. Slot 21 of the compiled
# vtable names that symbol, and Gate 3 requires every original-class entry
# to be backed by a binding, so map it explicitly — from the record only,
# with both record fields required to agree. The remaining inherited
# methods are covered by the systematic derivation below, which works
# from the same record method table under per-form accounting.
LEGACY_INIT_SYMBOL = '__ZN25IOMobileFramebufferLegacy4initEP12OSDictionary'

def apply_original_init_alias(bindings, audit):
    methods = audit['methods']
    require(int(methods[21]['slot']) == 21, 'E2 slot 21 identity mismatch')
    legacy_init = int(audit['original_init'], 16)
    require(int(methods[21]['address'], 16) == legacy_init,
            'E2 original_init disagrees with the slot 21 address')
    require(LEGACY_INIT_SYMBOL not in bindings or bindings[LEGACY_INIT_SYMBOL] == legacy_init,
            'Conflicting original init binding')
    bindings[LEGACY_INIT_SYMBOL] = legacy_init
    return bindings

bindings = apply_original_init_alias(bindings, audit)

# The E2 record qualifies all 358 original addresses in its method table,
# but its bindings map carries only the symbols the audit itself named.
# Gate 3 needs a binding for every original-class symbol the compiled
# object references: vtable entries for the original methods the
# component does not override, and the undefined imports left by the
# component's qualified base calls. Builds #93/#94 failed those entries
# one at a time (slot 21, then slot 44); the fix is not another alias
# per slot but one derivation pass over the whole table, in exactly
# these accounted forms — every derived address is the record's own
# method-table address for a cross-checked slot, and anything that
# matches no form is left unbound for Gate 3 to refuse:
#   * opaque slots: the generated header declares slot i (>= 168) as
#     IOMobileFramebufferLegacy::opaque{i} unless the slot is named or
#     abstract, so the compiled vtable names exactly
#     __ZN25IOMobileFramebufferLegacy9opaque{i}Ev there;
#   * named methods: manglings verified against the pinned class by
#     compiling a probe translation unit with the kernel toolchain;
#     each name must sit at its cross-checked slot (the three
#     IOService-region overrides systemWillShutdown / probe /
#     getWorkLoop occupy slots 79, 85, 111 in an order the builder
#     does not need to fix, because it reads the symbol the compiler
#     actually placed at each slot);
#   * qualified base calls: a stray original-class import is derived
#     only when it is the exact twin — same mangling with the class
#     segment exchanged — of the component's own override sitting in
#     the compiled vtable at a single slot.
# Where the record carries a standalone field for a slot (init, start,
# stop, newUserClient), the method-table address must agree with it.
NAMED_SLOT_BINDINGS = {
    '__ZN25IOMobileFramebufferLegacy13setPropertiesEP8OSObject': (44,),
    '__ZN25IOMobileFramebufferLegacy20getDisplayDimensionsEPjS0_': (249,),
    '__ZN25IOMobileFramebufferLegacy19completeCurrentSwapEv': (295,),
    '__ZN25IOMobileFramebufferLegacy17applyStateRequestEP26OriginalLegacyStateRequestb': (354,),
}
NAMED_SLOT_GROUP = {
    '__ZN25IOMobileFramebufferLegacy18systemWillShutdownEj': (79, 85, 111),
    '__ZN25IOMobileFramebufferLegacy5probeEP9IOServicePi': (79, 85, 111),
    '__ZNK25IOMobileFramebufferLegacy11getWorkLoopEv': (79, 85, 111),
}
STANDALONE_FIELDS = {21: 'original_init', 86: 'original_start',
                     87: 'original_stop', 141: 'original_new_user_client'}


def opaque_symbol(slot):
    return f'__ZN25IOMobileFramebufferLegacy9opaque{slot}Ev'


def derive_missing_bindings(bindings, audit, compiled, undefined):
    """Derive the bindings Gate 3 needs from the record method table.

    Mutates `bindings`; returns (derived, violations) where derived maps
    each new symbol to {'slot', 'address', 'provenance'} and violations
    lists every accounting failure found (derivation itself never
    guesses: an unaccounted symbol is simply not derived)."""
    methods = audit['methods']
    derived = {}
    violations = []

    def account(slot, name, provenance):
        address = int(methods[slot]['address'], 16)
        field = STANDALONE_FIELDS.get(slot)
        if field is not None and int(audit[field], 16) != address:
            violations.append(
                f'slot {slot} ({name}): record field {field} disagrees with the method table')
            return
        if name in bindings:
            if bindings[name] != address:
                violations.append(
                    f'slot {slot} ({name}): derived address conflicts with the existing binding')
            return
        bindings[name] = address
        derived[name] = {'slot': slot, 'address': hex(address), 'provenance': provenance}

    for slot, name in enumerate(compiled):
        if not name or '25IOMobileFramebufferLegacy' not in name:
            continue
        if slot >= 168 and name == opaque_symbol(slot):
            account(slot, name, 'opaque slot: exact generated prototype name for this slot')
        elif name in NAMED_SLOT_BINDINGS and slot in NAMED_SLOT_BINDINGS[name]:
            account(slot, name, 'named original method at its cross-checked slot')
        elif name in NAMED_SLOT_GROUP and slot in NAMED_SLOT_GROUP[name]:
            account(slot, name, 'named IOService-region override (slots 79/85/111 set)')

    twins = {}
    for slot, name in enumerate(compiled):
        if not name:
            continue
        for own, orig in (('__ZN19NativeLegacyDisplay', '__ZN25IOMobileFramebufferLegacy'),
                          ('__ZNK19NativeLegacyDisplay', '__ZNK25IOMobileFramebufferLegacy')):
            if name.startswith(own):
                twins.setdefault(name.replace(own, orig, 1), []).append(slot)
    for name in sorted(n for n in undefined
                       if 'IOMobileFramebufferLegacy' in n and n not in bindings):
        slots = twins.get(name, [])
        if len(slots) == 1:
            account(slots[0], name,
                    'qualified base call: twin of the component override at this slot')
    return derived, violations


# Optional provider imports ---------------------------------------------------
# The pinned component declares the Adreno fence query weak_import
# (NativeLegacyDisplay.cpp:54): its provider is the GPU driver, and
# both call sites test the symbol's address before calling (:175,
# :319), so "no provider selected" is a designed state. This board's
# first round selects no GPU provider. A dynamic link would leave the
# weak reference unresolved and bind it to 0 at load; the kernel link
# is static and cannot — Build #96's final link reported the weak
# import as a hard undefined symbol. The link-level equivalent of the
# absent-weak binding is an absolute binding to 0 in the bindings
# object: no code is provided, the address checks take the
# no-provider path, and the symbol stays out of the record bindings
# (it is not an original-class address). The allowlist is fixed at
# one symbol and gated on the evidence that makes the binding honest:
# the compiled object must import the symbol as a weak reference
# (n_desc N_WEAK_REF) and the pinned component source must still
# declare it weak_import with at least two address-availability
# guards. Any other shape is refused, never silently bound.
N_WEAK_REF = 0x0040
OPTIONAL_ABSENT_SYMBOLS = ('_native_adreno_fences',)


def optional_absent_bindings(undefined_desc, component_source):
    """Bind allowlisted optional provider imports to absent (0).

    `undefined_desc` maps each undefined import of the compiled
    component object to its Mach-O n_desc. Returns (absent,
    violations): absent maps each bound symbol to 0. A symbol the
    object does not import at all is not bound (nothing references
    it); an imported symbol is bound only under the gates documented
    above, and every gate failure is a violation."""
    absent = {}
    violations = []
    for name in OPTIONAL_ABSENT_SYMBOLS:
        if name not in undefined_desc:
            continue
        if not undefined_desc[name] & N_WEAK_REF:
            violations.append(
                f'Optional provider import {name} is not a weak reference '
                'in the compiled object; refusing to bind it absent')
            continue
        plain = name[1:] if name.startswith('_') else name
        declaration = component_source.split(plain, 1)[-1].split(';', 1)[0] \
            if plain in component_source else ''
        if 'weak_import' not in declaration:
            violations.append(
                f'Optional provider import {name} is not declared weak_import '
                'in the pinned component source; refusing to bind it absent')
            continue
        if component_source.count('&' + plain) < 2:
            violations.append(
                f'Optional provider import {name} has fewer than two '
                'address-availability guards in the component source; '
                'refusing to bind it absent')
            continue
        absent[name] = 0
    return absent, violations


# --- Gate 2: locate the verification original in the actual tree ------------
# Framework layout (scripts/unixnu/config.py, scripts/unixnu/ipsw.py): the
# tree is <out_root>/<device>/<os>/<work>/tree, the framework checkout is one
# level above out_root, and the decompressed original kernelcache lives at
# <out_root>/ipsw/<build>/kernelcache.decompressed. It is normally created at
# prelink time, which runs AFTER the archive steps, so on a fresh build it
# does not exist yet when this builder runs; in that case the builder
# materializes it through the framework's own CLI (`unixnu ipsw fetch
# KernelCache`), which streams the pinned IPSW member and verifies it
# against the board pin. Prelink later reuses the same file.
OUT_ROOT = ROOT.parents[3]
FRAMEWORK = ROOT.parents[4]
require((FRAMEWORK / 'unixnu').is_file(),
        f'Path resolution failed: no framework CLI at {FRAMEWORK}/unixnu (tree layout changed?)')
print(f'fuxi-legacy: framework_root={FRAMEWORK}')
print(f'fuxi-legacy: out_root={OUT_ROOT}')
original = None
original_mode = None
original_detail = None
staged = ROOT / 'build/xnu-prelink/native-owner-mobile-graphics-candidate.macho'
if not staged.exists():
    later = sorted((ROOT / 'build/xnu-prelink').glob('native-owner-ufs-cpu-desktop-*-candidate.macho'),
                   key=lambda f: f.stat().st_mtime) if (ROOT / 'build/xnu-prelink').is_dir() else []
    if later:
        staged = later[-1]
if staged.exists():
    original, original_mode = staged, 'staged-candidate'
else:
    # The framework passes the IPSW build to archive steps as
    # UNIXNU_IPSW_BUILD (scripts/unixnu/kernel.py, xnu_env), and the cache
    # path is <out_root>/ipsw/<build>/kernelcache.decompressed
    # (scripts/unixnu/ipsw.py). Locate it exactly from that variable, never
    # from a hardcoded build string or a directory glob.
    ipsw_build = os.environ.get('UNIXNU_IPSW_BUILD')
    require(bool(ipsw_build), 'UNIXNU_IPSW_BUILD is missing from the archive environment')
    expected = OUT_ROOT / 'ipsw' / ipsw_build / 'kernelcache.decompressed'
    override = os.environ.get('UNIXNU_KERNELCACHE')
    cache_path = Path(override) if override else expected
    print(f'fuxi-legacy: ipsw_build={ipsw_build}')
    print(f'fuxi-legacy: kernelcache_path={cache_path}')
    print(f'fuxi-legacy: kernelcache_exists={cache_path.is_file()}')
    if not (cache_path.is_file() and sha(cache_path) == KERNELCACHE_SHA256):
        cli = FRAMEWORK / 'unixnu'
        command = [str(cli), 'ipsw', 'fetch', 'KernelCache']
        state = OUT_ROOT / 'state.json'
        if state.is_file():
            device = json.loads(state.read_text()).get('device')
            if device:
                command += ['--device', device]
        result = subprocess.run(command, cwd=FRAMEWORK, capture_output=True, text=True, timeout=900)
        require(result.returncode == 0,
                'Framework CLI failed to materialize the original kernelcache: '
                + (result.stderr.strip() or result.stdout.strip()))
        original_detail = 'materialized via the framework CLI (unixnu ipsw fetch KernelCache)'
        print(f'fuxi-legacy: kernelcache_exists_after_cli={cache_path.is_file()}')
    require(cache_path.is_file() and sha(cache_path) == KERNELCACHE_SHA256,
            'No verification original found in the build tree: no staged prelink candidate, no '
            'decompressed kernelcache matching the OS profile pin, and the framework CLI could not '
            'materialize one; refusing to build on unverified inputs')
    print(f'fuxi-legacy: kernelcache_sha256={sha(cache_path)}')
    original, original_mode = cache_path, 'original-kernelcache'
require(original is not None,
        'No verification original found in the build tree; refusing to build on unverified inputs')
original_blob = original.read_bytes()
fam_sha, _ftext = family_text_sha256(original_blob)
print(f'fuxi-legacy: family_text_sha256={fam_sha}')
require(fam_sha == audit['family_text_sha256'],
        f'Family __TEXT_EXEC sha256 {fam_sha} does not match the E2 record {audit["family_text_sha256"]}')
candidate_names = None
if original_mode == 'staged-candidate':
    original_image = macho(original_blob)
    candidate_names = {n: v for v, group in exports(original_blob, original_image).items() for n in group}

# --- Generate the ABI header the component compiles against ------------------
# The class declaration and slot prototypes are the component's own
# compile contract (it includes this header by name). Layout constants
# in it are the original class's, for this OS profile; every ADDRESS
# (bindings, method table) comes from the E2 record alone.
header = '''// SPDX-License-Identifier: BSD-2-Clause-Patent
// Opaque ABI storage for the exact original class, not source-level access
// to its private fields. The actual original metadata supplies its full
// Framebuffer/Service/IOService ancestry. Only qualified base prototypes may
// be called from source; opaque entries are original dispatch targets only.
#pragma once
#include <IOKit/IOService.h>
#include <libkern/libkern.h>
struct OriginalLegacySwapRequest;
// Original state request (skip/requested and skip/powered word pairs, then the changed flag) taken by the state setter.
struct OriginalLegacyStateRequest {uint32_t skipRequested,requested,skipPowered,powered;uint8_t changed;uint8_t pad[11];};
// Original field offsets: vsync client queue in the display; rectangles, layer masks (updated, disabled, background),
// options, dimensions and surfaces in a swap request.
static constexpr unsigned kLegacyVsyncClients=5592;
static constexpr unsigned kRequestRect0=17,kRequestRect1=81,kRequestMasks=792,kRequestOptions=804,kRequestDims=816,kRequestSurfaces=2624;
// Backend leaves: pure original slots the owned backend implements only as guards.
#define NATIVE_LEGACY_LEAVES(LEAF) LEAF(211) LEAF(245) LEAF(246) LEAF(306) LEAF(307) LEAF(338) LEAF(345)
class IOMobileFramebufferLegacy : public IOService {
 OSDeclareAbstractStructors(IOMobileFramebufferLegacy)
 unsigned char originalPrivate[0x18a0-sizeof(IOService)];
public:
 // Both fields are qualified by the complete original slot-249 getter.
 // This modifies this object's own mode state, never a vtable or executable.
 void installBootDimensions(uint32_t width,uint32_t height) {
  *reinterpret_cast<uint32_t *>(reinterpret_cast<unsigned char *>(this)+5808)=width;
  *reinterpret_cast<uint32_t *>(reinterpret_cast<unsigned char *>(this)+5812)=height;
 }
 const OriginalLegacySwapRequest *pendingSwapRequest() const {
  const OriginalLegacySwapRequest *request=nullptr;
  memcpy(&request,reinterpret_cast<const unsigned char *>(this)+5480,sizeof(request));return request;
 }
 // The real normal scanout backend removes its pending head before calling
 // slot 295. Slot 312 is a discard path (terminal state 8), not presentation.
 // The queue is a tail queue (head at +5480, tail pointer at +5488, each request's next at +2960 and previous-link at +2968): taking the head
 // moves the next request, if a client already queued one behind it, up to the head. The original queue's reference
 // moves to the current-swap slot for the original completion body.
 bool activateOnlyPendingSwap(const OriginalLegacySwapRequest *request) {
  auto self=reinterpret_cast<unsigned char *>(this);
  auto bytes=reinterpret_cast<const unsigned char *>(request);
  const void *current=nullptr,*head=nullptr,*tail=nullptr,*next=nullptr,*previous=nullptr;
  memcpy(&current,self+5472,8);memcpy(&head,self+5480,8);memcpy(&tail,self+5488,8);
  if(!request || current || head!=request)return false;
  memcpy(&next,bytes+2960,8);memcpy(&previous,bytes+2968,8);
  if(previous!=self+5480)return false;
  if(next) {
   const void *link=self+5480;
   memcpy(const_cast<unsigned char *>(reinterpret_cast<const unsigned char *>(next))+2968,&link,8);
  } else if(tail!=bytes+2960)return false;
  memcpy(self+5472,&request,8);
  if(next) {memcpy(self+5480,&next,8);}
  else {const void *empty=nullptr,*emptyTail=self+5480;memcpy(self+5480,&empty,8);memcpy(self+5488,&emptyTail,8);}
  return true;
 }
 void free() override;
 bool init(OSDictionary *properties=nullptr) override;
 IOReturn setProperties(OSObject *) override;
 void systemWillShutdown(IOOptionBits) override;
 IOService *probe(IOService *,SInt32 *) override;
 bool start(IOService *) override;
 void stop(IOService *) override;
 IOWorkLoop *getWorkLoop() const override;
 IOReturn newUserClient(task_t,void *,UInt32,IOUserClient **) override;
 IOReturn setPowerState(unsigned long,IOService *) override;
'''
for i in range(168, 358):
    if i == 184:
        header += ' virtual bool isMainDisplay();\n'
    elif i == 188:
        header += ' virtual IOReturn getDotPitch(uint32_t *);\n'
    elif i == 213:
        header += ' virtual IOReturn supportedFrameInfo(uint32_t,uint32_t *,char *,uint32_t *)=0;\n'
    elif i == 249:
        header += ' virtual void getDisplayDimensions(uint32_t *,uint32_t *);\n'
    elif i == 290:
        header += ' virtual void kickSwapQueue();\n'
    elif i == 296:
        header += ' virtual bool validateSwap(const OriginalLegacySwapRequest *);\n'
    elif i == 295:
        header += ' virtual void completeCurrentSwap();\n'
    elif i == 337:
        header += ' virtual IOReturn collectCompletionReports(uint32_t,void *,uint32_t *,uint32_t)=0;\n'
    elif i == 288:
        header += ' virtual bool startHardware();\n'
    elif i == 354:
        header += ' virtual int applyStateRequest(OriginalLegacyStateRequest *,bool);\n'
    elif i == 301:
        header += ' virtual bool getRefreshAttributes(uint64_t *,bool);\n'
    elif i in pure:
        header += f' virtual __attribute__((noreturn)) void opaque{i}()=0;\n'
    else:
        header += f' virtual __attribute__((deprecated("Unclassified ABI: never call from source"))) void opaque{i}();\n'
header += '};\nstatic_assert(sizeof(IOMobileFramebufferLegacy)==0x18a0,"Actual original instance extent");\n'
(OUT / 'OriginalLegacyFramebufferABI.h').write_text(header)

# --- Compile the component object --------------------------------------------
print(run(['python3', ROOT / 'scripts/build-arm-driver.py', 'NativeLegacyDisplay'], text=True), end='')
obj = OUT / 'NativeLegacyDisplay.o'
raw = obj.read_bytes()
image = macho(raw)
st = next(p for c, p, _ in image['commands'] if c == 2)
sy, count, strings, _ = struct.unpack_from('<4I', raw, st + 8)
symbols = []
undefined_desc = {}
for i in range(count):
    ix, kind, section, desc, va = struct.unpack_from('<IBBHQ', raw, sy + i * 16)
    name = raw[strings + ix:raw.index(b'\0', strings + ix)].decode()
    symbols.append((name, va, kind))
    if kind == 1:
        undefined_desc[name] = desc
vtable = next(va for name, va, _ in symbols if name == '__ZTV19NativeLegacyDisplay')
relocations = {}
for segment in image['segments']:
    for sec in segment['sections']:
        if sec['va'] <= vtable < sec['va'] + sec['size']:
            ro, rc = struct.unpack_from('<2I', raw, sec['command_offset'] + 56)
            for i in range(rc):
                offset, bits = struct.unpack_from('<2I', raw, ro + i * 8)
                if bits >> 27 & 1 and bits >> 28 == 0 and bits >> 25 & 3 == 3:
                    relocations[sec['va'] + offset] = symbols[bits & 0xffffff][0]
compiled = [relocations.get(vtable + 16 + i * 8) for i in range(358)]
require(all(compiled) and vtable + 16 + 358 * 8 not in relocations, 'Exact owned 358-entry vtable')

# --- Gate 3: the compiled vtable against the record --------------------------
undefined = {n for n, _, k in symbols if k == 1}
derived_bindings, violations = derive_missing_bindings(bindings, audit, compiled, undefined)
for name in sorted(derived_bindings, key=lambda n: derived_bindings[n]['slot']):
    entry = derived_bindings[name]
    print(f"fuxi-legacy: derived binding slot {entry['slot']} {name} -> {entry['address']} "
          f"({entry['provenance']})")
print(f'fuxi-legacy: {len(derived_bindings)} binding(s) derived from the record method table')
owned, inherited = [], []
for i, name in enumerate(compiled):
    expected = int(methods[i]['address'], 16)
    if name.startswith(('__ZN19NativeLegacyDisplay', '__ZNK19NativeLegacyDisplay')):
        owned.append(i)
        if i not in OWNED_CONCRETE and i not in pure:
            violations.append(f'Component overrides an unqualified slot {i}')
    elif '25IOMobileFramebufferLegacy' in name:
        if name not in bindings:
            violations.append(f'Original-class vtable entry {i} ({name}) has no record binding')
        elif bindings[name] != expected:
            violations.append(
                f'Original-class vtable entry {i} ({name}) disagrees with the record address')
        else:
            inherited.append(i)
    elif i in pure:
        if name != '___cxa_pure_virtual':
            violations.append(f'Abstract slot {i} resolves to unexpected target {name}')
    else:
        if i >= 168:
            violations.append(f'Unclassified original-region vtable entry {i}: {name}')
        elif candidate_names is not None and candidate_names.get(name) != expected:
            violations.append(
                f'Inherited native base symbol {i} ({name}) disagrees with the candidate')
if violations:
    for violation in violations:
        print(f'fuxi-legacy: GATE 3 VIOLATION: {violation}')
    raise SystemExit(f'Gate 3 failed: {len(violations)} violation(s), listed above in full')
require(set(bindings) <= undefined,
        'Component object does not import every record binding: '
        + ', '.join(sorted(set(bindings) - undefined)))
stray = {n for n in undefined if 'IOMobileFramebufferLegacy' in n and n not in bindings}
require(not stray, 'Component object imports unqualified original-class symbols: ' + ', '.join(sorted(stray)))

# --- Optional provider imports: bind the unselected ones absent --------------
component_source = (ROOT / 'drivers/GopFramebuffer/NativeLegacyDisplay.cpp').read_text()
absent_bindings, absent_violations = optional_absent_bindings(undefined_desc, component_source)
if absent_violations:
    for violation in absent_violations:
        print(f'fuxi-legacy: GATE 3 VIOLATION: {violation}')
    raise SystemExit(f'Gate 3 failed: {len(absent_violations)} optional-import violation(s), listed above in full')
for name in sorted(absent_bindings):
    print(f'fuxi-legacy: optional provider import {name}: no provider selected on this board; '
          'binding it absent (0) under the weak-import gates')

# --- Bindings object ----------------------------------------------------------
asm = OUT / 'original-bindings.S'
asm.write_text(''.join(f'.globl {name}\n.set {name}, {va:#x}\n'
                       for name, va in sorted({**bindings, **absent_bindings}.items())))
sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
run(['xcrun', 'clang', '-target', TRIPLE, '-isysroot', sdk, '-c', asm, '-o', OUT / 'original-bindings.o'])

# --- Late-ify the component object --------------------------------------------
llvm = Path(run(['brew', '--prefix', 'llvm'], text=True).strip()) / 'bin'
late = OUT / 'NativeLegacyDisplay.late.o'
run([llvm / 'llvm-objcopy', '--remove-section=__DATA,__mod_init_func',
     '--globalize-symbol=__GLOBAL__sub_I_NativeLegacyDisplay.cpp', obj, late])


def code(data, info):
    sec = next(s for g in info['segments'] for s in g['sections'] if s['name'] == '__text')
    return data[sec['fileoff']:sec['fileoff'] + sec['size']]


require(code(raw, image) == code(late.read_bytes(), macho(late.read_bytes())),
        'Only owned initializer section registration changes')

# --- Compile the board glue from the IOPlatformExpert record -------------------
record_path = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
r = json.loads(record_path.read_text().strip().rstrip(','))
cmd = []
args = r['arguments']
i = 0
source = ROOT / 'kits/fuxi/FuxiLegacyDisplayProbe.cpp'
glue_obj = OUT / 'FuxiLegacyDisplayProbe.o'
while i < len(args):
    value = args[i]
    if value == r['file']:
        cmd.append(str(source))
    elif value == '-o':
        cmd += ['-o', str(glue_obj)]
        i += 1
    elif value == '-Xclang' and args[i + 1].startswith('-W'):
        i += 1
    elif not value.startswith('-W'):
        cmd.append(value)
    i += 1
cmd += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-unnecessary-virtual-specifier',
        '-Wno-c99-designator', '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
        '-I', str(ROOT / '.cache/xnu-work/osfmk')]
run(cmd, cwd=r['directory'])

# --- Archive exactly the three display members ---------------------------------
archive = OUT / 'libNativeLegacyDisplay.late.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, late, OUT / 'original-bindings.o', glue_obj])

sources = [ROOT / 'drivers/GopFramebuffer/NativeLegacyDisplay.cpp',
           ROOT / 'drivers/GopFramebuffer/NativeLegacyRequest.h',
           ROOT / 'drivers/GopFramebuffer/NativeGOPWire.h',
           ROOT / 'drivers/GopFramebuffer/NativeHalfCodes.h',
           source,
           RECORD,
           Path(__file__).resolve()]
(OUT / 'build-report.json').write_text(json.dumps(dict(
    source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
    generated_abi_sha256=sha(OUT / 'OriginalLegacyFramebufferABI.h'),
    abi_record_sha256=RECORD_SHA256,
    verification_original_mode=original_mode,
    verification_original_detail=original_detail,
    verification_original_sha256=sha(original),
    family_text_sha256=fam_sha,
    compiled_object_sha256=sha(obj), late_object_sha256=sha(late),
    glue_object_sha256=sha(glue_obj), archive_sha256=sha(archive),
    bindings={n: hex(v) for n, v in bindings.items()}, virtual_entries=358,
    optional_absent_bindings={n: hex(v) for n, v in absent_bindings.items()},
    optional_absent_provenance='Provider hooks the pinned component declares weak_import and calls '
                               'only behind address-availability checks, bound to 0 (absent) because '
                               'this board selects no provider for them in round 1 and the static '
                               'kernel link cannot leave a weak reference unresolved (Build #96). No '
                               'implementation is provided; the component takes its designed '
                               'no-provider path. The set is the fixed allowlist '
                               'OPTIONAL_ABSENT_SYMBOLS, each entry gated on the compiled object '
                               'importing the symbol as a weak reference (n_desc N_WEAK_REF), on the '
                               'weak_import declaration, and on the guarded call sites.',
    derived_bindings=derived_bindings,
    derived_bindings_provenance='Bindings absent from the E2 record bindings map were derived '
                                'from the record method table only, in the accounted forms '
                                'documented at derive_missing_bindings (the slot-21 init alias, '
                                'exact opaque slot names, compiler-verified named methods at '
                                'cross-checked slots, qualified base calls matched to the '
                                'component override twin at the same slot). Every derived '
                                'address is the record address for its slot, cross-checked '
                                'against the record standalone fields where one exists.',
    owned_entries=owned, inherited_original_entries=inherited,
    guarded_backend_leaves=[i for i in pure if i not in (213, 337)],
    header_layout_provenance='Class declaration, slot prototypes and original layout constants are the '
                             'component compile contract for this OS profile (the component includes the '
                             'generated header by name); all addresses and the method table come from the '
                             'fuxi E2 record alone. The layout constants were not independently re-derived '
                             'in E2; several were byte-checked there against the fuxi candidate.',
    record_provenance='E2 record f5d3f629: binary bindings derived from the fuxi candidate; its '
                      'runtime-metadata leg was substituted under the audit fallback rule and the '
                      'instance size is a carried value (see the record itself).',
    original_instructions_modified=False, driver_initialized=False, display_presented=False, desktop=False),
    indent=2) + '\n')
print('Built fuxi Legacy display archive from the E2 record; runtime lifecycle unqualified')
