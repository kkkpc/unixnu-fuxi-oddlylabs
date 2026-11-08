#!/usr/bin/env python3
"""Regression test for the legacy display link contract (Build #96).

Build #95's fix gave the 18 component callbacks the C linkage the
component declares; Build #96's final kernel link then failed on the
next two boundaries of the same contract:

  * the two probe entry points. The framework patch series declares
    them as plain C in bsd/kern/bsd_init.c
    (patches/xnu/offline-component-load-probes.patch,
    patches/xnu/offline-legacy-start.patch), but the glue defined
    them as plain C++, exporting only the mangled names;
  * _native_adreno_fences, the component's weak_import GPU fence
    query (NativeLegacyDisplay.cpp:54), whose call sites test the
    symbol's address before calling (:175, :319). Round 1 selects no
    GPU provider, and the static kernel link cannot leave a weak
    reference unresolved, so the builder binds the allowlisted
    optional import to absent (0) — under gates, never as a stub.

This test checks, with no toolchain:

  1. the glue's structure: both probe definitions and all 18
     component callbacks sit inside extern "C" regions, in separate
     regions, with the file's braces balanced;
  2. the builder's optional_absent_bindings decision (extracted from
     the builder source the same way test-legacy-derivations.py
     extracts the derivation): the real contract shape binds absent;
     a non-weak import, a missing weak_import declaration, or a
     missing address guard each refuse; a symbol the object does not
     import is not bound; a non-allowlisted import is never bound.

The component-source fixture below mirrors the pinned component's
declaration and guarded call sites verbatim in shape; the builder
itself re-checks the real source at build time, which is the gate
that runs against the pinned tree.

Run: python3 scripts/test-legacy-linkage.py (exit 0 = pass).
"""
import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / 'build-fuxi-legacy-display.py'
GLUE = HERE.parent / 'package' / 'FuxiLegacyDisplayProbe.cpp'

EXTRACT_NAMES = {'N_WEAK_REF', 'OPTIONAL_ABSENT_SYMBOLS', 'optional_absent_bindings'}

COMPONENT_FIXTURE = (
    'extern "C" bool native_adreno_fences(uint32_t *submitted,uint32_t *retired) '
    '__attribute__((weak_import));\n'
    'void note() { uint32_t submitted = 0, retired = 0; '
    'if(&native_adreno_fences && native_adreno_fences(&submitted,&retired)) {} }\n'
    'bool gpuWrote() { if(!&native_adreno_fences) return true; return false; }\n')

CALLBACKS = [
    'native_legacy_backend_guard', 'native_legacy_gop_mapping_observed',
    'native_legacy_registration_observed', 'native_legacy_client_enter',
    'native_legacy_client_observed', 'native_legacy_pm_observed',
    'native_legacy_frame_observed', 'native_legacy_frame_colors_observed',
    'native_legacy_surface_rejected', 'native_legacy_prepare_scanout',
    'native_legacy_copy_timing_observed', 'native_legacy_retirement_observed',
    'native_legacy_gpu_offer', 'native_legacy_gpu_fallback_observed',
    'native_legacy_swap_stage', 'native_legacy_swap_validation_observed',
    'native_legacy_transfer_observed', 'native_legacy_vsync_observed',
]


def load_builder_pieces():
    tree = ast.parse(BUILDER.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in EXTRACT_NAMES:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in EXTRACT_NAMES for t in node.targets):
            nodes.append(node)
    namespace = {'require': lambda c, m: (_ for _ in ()).throw(AssertionError(m)) if not c else None}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BUILDER), 'exec'), namespace)
    return namespace


def extern_c_regions(text):
    """Region text per extern "C" block, brace-matched from its opener
    through the end of its closing line (which carries the marker
    comment naming the block)."""
    regions = []
    for match in re.finditer(r'extern "C" \{', text):
        depth = 0
        i = match.end() - 1
        while i < len(text):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        newline = text.find('\n', i)
        regions.append(text[match.start():newline if newline != -1 else len(text)])
    return regions


def main():
    failures = []

    def check(name, condition, detail=''):
        print(f'{"PASS" if condition else "FAIL"}: {name}' + (f' ({detail})' if detail and not condition else ''))
        if not condition:
            failures.append(name)

    glue = GLUE.read_text()
    check('glue braces balanced', glue.count('{') == glue.count('}'))
    regions = extern_c_regions(glue)
    callback_region = next((r for r in regions if '(the 18 component callbacks above)' in r), '')
    probe_region = next((r for r in regions if '(the two probe entry points above)' in r), '')
    check('glue has both marked extern "C" regions', bool(callback_region) and bool(probe_region),
          f'{len(regions)} extern "C" blocks found')
    defined_callbacks = [name for name in CALLBACKS
                         if re.search(rf'\b{name}\s*\([^)]*\)\s*\{{', callback_region)]
    check('all 18 callbacks defined inside the callback region',
          len(defined_callbacks) == 18, f'{len(defined_callbacks)} found')
    check('no probe definition inside the callback region',
          'native_legacy_display_probe(void) {' not in callback_region
          and 'native_legacy_display_late_probe(void) {' not in callback_region)
    check('early probe defined inside the probe region',
          'void native_legacy_display_probe(void) {' in probe_region)
    check('late probe defined inside the probe region',
          'void native_legacy_display_late_probe(void) {' in probe_region)

    ns = load_builder_pieces()
    decide = ns['optional_absent_bindings']
    weak = ns['N_WEAK_REF']
    name = '_native_adreno_fences'

    absent, violations = decide({name: weak}, COMPONENT_FIXTURE)
    check('weak import under the full contract binds absent',
          absent == {name: 0} and not violations, f'{absent} {violations}')

    absent, violations = decide({name: 0}, COMPONENT_FIXTURE)
    check('non-weak import is refused', absent == {} and len(violations) == 1)

    absent, violations = decide({}, COMPONENT_FIXTURE)
    check('unimported symbol is not bound', absent == {} and not violations)

    absent, violations = decide({name: weak}, COMPONENT_FIXTURE.replace('__attribute__((weak_import))', ''))
    check('missing weak_import declaration is refused', absent == {} and len(violations) == 1)

    one_guard = COMPONENT_FIXTURE.replace('if(!&native_adreno_fences)', 'if(false)')
    absent, violations = decide({name: weak}, one_guard)
    check('a single address guard is refused', absent == {} and len(violations) == 1)

    absent, violations = decide({'_native_ufs_dpu_map': weak}, COMPONENT_FIXTURE)
    check('non-allowlisted import is never bound', absent == {} and not violations)

    print('legacy linkage regression:', 'FAIL' if failures else 'PASS')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
