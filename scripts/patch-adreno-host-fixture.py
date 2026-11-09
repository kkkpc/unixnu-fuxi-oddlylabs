#!/usr/bin/env python3
"""Apply the small host-only XNU memory double needed by the pinned Adreno740 tests."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--tree", type=Path, required=True, help="resolved UniXNU target tree")
args = parser.parse_args()
root = args.tree.resolve()
fixture = root / "drivers/Adreno740/tests/XnuMemoryFixture.h"
needle = "inline void *IOMallocZero(size_t bytes) {return std::calloc(1,bytes);}\n"
replacement = needle + "inline void IOFree(void *ptr,size_t) {std::free(ptr);}\n"
task_needle = "using task_t=void *;\n"
task_replacement = task_needle + "inline task_t current_task() {return kernel_task;}\ninline int task_get_gpu_role(task_t) {return 0;}\n"
resource_private = root / "build/turnip-darwin-host/host-include/sys/resource_private.h"
checker = root / "scripts/check-turnip-darwin-host.py"
service = root / "drivers/Adreno740/tests/hostsim/host_gpu_service.cpp"
resource_private_text = """/* Host-only subset of the fuxi XNU GPU-role contract. */
#pragma once
#define PRIO_DARWIN_GPU_BACKGROUND 8
#define PRIO_DARWIN_GPU_UTILITY 9
"""

if not fixture.is_file():
    raise SystemExit(f"Adreno740 host fixture missing: {fixture}")
text = fixture.read_text()
if "inline void IOFree(void *ptr,size_t)" in text:
    print("PASS: Adreno740 host fixture already provides IOFree")
elif needle in text:
    fixture.write_text(text.replace(needle, replacement, 1))
    print("PASS: added host-only IOFree double to the pinned Adreno740 fixture")
else:
    raise SystemExit("Adreno740 host fixture changed: IOFree insertion anchor is absent")

text = fixture.read_text()
if "inline int task_get_gpu_role(task_t)" in text:
    print("PASS: Adreno740 host fixture already provides the neutral GPU role")
elif task_needle in text:
    fixture.write_text(text.replace(task_needle, task_replacement, 1))
    print("PASS: added host-only current task with neutral GPU role")
else:
    raise SystemExit("Adreno740 host fixture changed: task insertion anchor is absent")

resource_private.parent.mkdir(parents=True, exist_ok=True)
if resource_private.exists() and resource_private.read_text() != resource_private_text:
    raise SystemExit(f"unexpected existing host GPU-role header: {resource_private}")
resource_private.write_text(resource_private_text)
print("PASS: published host-only sys/resource_private.h with fuxi GPU roles 8/9")

checker_needle = "'NativeAdrenoRing', 'NativeAdrenoSubmit',\n             'NativeAdrenoUserClient'"
checker_replacement = "'NativeAdrenoRing', 'NativeAdrenoSubmit', 'NativeAdrenoPreempt',\n             'NativeAdrenoUserClient'"
checker_text = checker.read_text()
if "'NativeAdrenoSubmit', 'NativeAdrenoPreempt'" in checker_text:
    print("PASS: Turnip host checker already compiles NativeAdrenoPreempt")
elif checker_needle in checker_text:
    checker.write_text(checker_text.replace(checker_needle, checker_replacement, 1))
    print("PASS: added NativeAdrenoPreempt to the Turnip host core")
else:
    raise SystemExit("Turnip host checker changed: NativeAdreno core-list anchor is absent")

service_needle = "extern \"C\" {\n/* The kernel KPI the user client names an import's task by; the host stand-in is this process. */"
service_replacement = "extern \"C\" {\nuint64_t native_adreno_now_us(void) {return cnow(nullptr);}\n/* The kernel KPI the user client names an import's task by; the host stand-in is this process. */"
service_text = service.read_text()
if "uint64_t native_adreno_now_us(void)" in service_text:
    print("PASS: Adreno host service already exports the diagnostic clock")
elif service_needle in service_text:
    service.write_text(service_text.replace(service_needle, service_replacement, 1))
    print("PASS: exported the host service's monotonic diagnostic clock")
else:
    raise SystemExit("Adreno host service changed: diagnostic-clock anchor is absent")


# The owner asked to skip host smoke tests in the bring-up CI. gen-turnip-replay.py
# still needs the checker's build products (libhostiokit.dylib + plugin_smoke), so
# retain only that fixture construction and return before the validation suite.
checker_text = checker.read_text()
smoke_compile = """smoke = out / 'vulkan_smoke'
subprocess.run(['xcrun', 'clang', '-std=c11', '-O1', '-I', '/opt/homebrew/include', sim / 'vulkan_smoke.c', '-o', smoke,
                '-Wl,-rpath,' + str(out)], check=True)

"""
if "smoke = out / 'vulkan_smoke'" in checker_text:
    if smoke_compile not in checker_text:
        raise SystemExit("Turnip host checker changed: Vulkan smoke compile block anchor is absent")
    checker_text = checker_text.replace(
        smoke_compile,
        "# fuxi bring-up CI: skip the standalone Vulkan smoke binary; replay needs only plugin_smoke.\n",
        1,
    )

fixture_exit_anchor = """subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-I', ROOT / 'drivers/AdrenoMetal', '-I', ROOT / '.cache/mesa-work/include',
                '-I', ROOT / 'build/turnip-smoke',
                sim / 'plugin_smoke.cpp', '-o', plugin_smoke], check=True)
env = dict(os.environ, DYLD_INSERT_LIBRARIES=str(shim), MESA_LOG='')
"""
fixture_exit_replacement = """subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-I', ROOT / 'drivers/AdrenoMetal', '-I', ROOT / '.cache/mesa-work/include',
                '-I', ROOT / 'build/turnip-smoke',
                sim / 'plugin_smoke.cpp', '-o', plugin_smoke], check=True)
print('PASS: built Turnip replay fixture; fuxi bring-up CI skips host smoke tests')
sys.exit(0)
env = dict(os.environ, DYLD_INSERT_LIBRARIES=str(shim), MESA_LOG='')
"""
if "fuxi bring-up CI skips host smoke tests" in checker_text:
    print("PASS: Turnip host checker already skips validation smoke tests")
elif fixture_exit_anchor in checker_text:
    checker_text = checker_text.replace(fixture_exit_anchor, fixture_exit_replacement, 1)
    print("PASS: Turnip host checker reduced to replay-fixture build; smoke tests skipped")
else:
    raise SystemExit("Turnip host checker changed: replay-fixture exit anchor is absent")

checker.write_text(checker_text)
