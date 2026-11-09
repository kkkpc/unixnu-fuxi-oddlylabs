#!/usr/bin/env python3
"""Backport the current upstream fast-path behavior to the pinned Adreno Metal tree.

The fast bring-up image needs the target iOS Turnip library and Metal plugin. The
host replay capture is diagnostic-only in current upstream (--no-replay), so the
pinned 6ae4c252 tree omits gen-turnip-replay.py and any stale TurnipReplay.h.

The pinned AdrenoMetal a0f0287 source also defines the iPadOS 27 QuartzCore
patchFramebufferBranch() helper for every architecture even though its only call
is inside #if defined(__arm64e__). The fuxi iPadOS 17 target is plain arm64 and
builds with -Werror, so that helper must be compiled only for arm64e. This keeps
the iOS 17 runtime path unchanged instead of disabling warnings or deleting the
iOS 27 workaround.
"""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--tree", type=Path, required=True, help="resolved UniXNU target tree")
args = parser.parse_args()
root = args.tree.resolve()
builder = root / "scripts/build-adreno-metal-plugin.py"

if not builder.is_file():
    raise SystemExit(f"Adreno Metal builder missing: {builder}")

text = builder.read_text()
marker = "optional Turnip host replay capture skipped for fuxi bring-up"
legacy = """# Turnip's first submission, recorded on the host, for the plugin's prefix replay (build/turnip-smoke/TurnipReplay.h).
subprocess.run(['python3', ROOT / 'scripts/gen-turnip-replay.py'], check=True)
"""
replacement = """# fuxi fast bring-up: current upstream exposes this host replay as optional diagnostics (--no-replay).
# The target plugin accepts an absent TurnipReplay.h through its existing optional include path.
(ROOT / 'build/turnip-smoke/TurnipReplay.h').unlink(missing_ok=True)
print('PASS: optional Turnip host replay capture skipped for fuxi bring-up')
"""

if marker in text:
    print("PASS: pinned Adreno Metal builder already skips the optional replay capture")
elif legacy in text:
    builder.write_text(text.replace(legacy, replacement, 1))
    print("PASS: backported upstream --no-replay behavior to the pinned Adreno Metal builder")
else:
    raise SystemExit("Adreno Metal builder changed: replay-call anchor is absent")

plugin = root / "drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm"
if not plugin.is_file():
    raise SystemExit(f"Adreno Metal plugin missing: {plugin}")

source = plugin.read_text()
guarded_marker = "#if defined(__arm64e__)\nstatic unsigned patchFramebufferBranch(uintptr_t slide)"
legacy_helper = """static unsigned patchFramebufferBranch(uintptr_t slide) {
    const uintptr_t site = 0x184461928 + slide;
    uint32_t word = 0;
    if (!readTask(site, &word, sizeof word)) return 0x6E40;
    if (word == 0xd503201f) return 0x6E42;
    if (word != 0x37000608) return 0x6E41;
    const vm_address_t page = site & ~(uintptr_t)(vm_page_size - 1);
    if (vm_protect(mach_task_self(), page, vm_page_size, FALSE, VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY) != KERN_SUCCESS) return 0x6E51;
    const uint32_t nop = 0xd503201f;
    const bool wrote = vm_write(mach_task_self(), site, (vm_offset_t)&nop, sizeof nop) == KERN_SUCCESS;
    const bool restored = vm_protect(mach_task_self(), page, vm_page_size, FALSE, VM_PROT_READ | VM_PROT_EXECUTE) == KERN_SUCCESS;
    sys_icache_invalidate((void *)site, sizeof nop);
    if (!wrote) return 0x6E52;
    if (!restored) return 0x6E53;
    return 0x6E42;
}
"""
guarded_helper = "#if defined(__arm64e__)\n" + legacy_helper + "#endif\n"

if guarded_marker in source:
    print("PASS: iPadOS 27 framebuffer helper already excluded from arm64")
elif legacy_helper in source:
    plugin.write_text(source.replace(legacy_helper, guarded_helper, 1))
    print("PASS: restricted iPadOS 27 framebuffer helper to arm64e; fuxi arm64 keeps the iOS 17 path")
else:
    raise SystemExit("Adreno Metal plugin changed: framebuffer-helper anchor is absent")
