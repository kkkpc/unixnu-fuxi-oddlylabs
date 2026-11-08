#!/usr/bin/env python3
"""Regression test for the legacy display link contract (Builds #96-#99).

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
    symbol's address before calling (:175, :319).

For the fence query, Build #96 bound the allowlisted import to
absent (0) in the bindings object. Build #99's formal link disproved
that design: both call sites are direct calls, so the linker must
resolve the branch target before any address check can run, and it
failed with an arm64_b26 fixup error (note()+0x44, from
0xFFFFFFF00BF7B2E8 to 0x00000000). The contract is now that the
board glue provides the query itself — a real extern "C" function
with the component's exact ABI returning false, the no-provider
answer — and the builder emits no binding for it at all.

This test checks, with no toolchain:

  1. the glue's structure: both probe definitions and all 18
     component callbacks sit inside extern "C" regions, in separate
     regions, with the file's braces balanced; the fence query sits
     in its own marked extern "C" region, with the exact component
     signature and an unconditional false return;
  2. the builder no longer carries the absent-binding mechanism
     whose generated .set to 0 caused the Build #99 fixup error;
  3. the builder's board_provided_imports decision (extracted from
     the builder source the same way test-legacy-derivations.py
     extracts the derivation): the real contract shape is provided;
     a non-weak import, a missing weak_import declaration, a
     missing address guard, a missing or non-conforming glue
     definition (wrong signature, C++ linkage, a true return) each
     refuse; a symbol the object does not import needs no provider;
     a non-allowlisted import is never provided.

The component-source fixture below mirrors the pinned component's
declaration and guarded call sites verbatim in shape; the builder
itself re-checks the real sources at build time, which is the gate
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

EXTRACT_NAMES = {'N_WEAK_REF', 'BOARD_PROVIDED_SYMBOLS', 'extern_c_regions', 'board_provided_imports'}

COMPONENT_FIXTURE = (
    'extern "C" bool native_adreno_fences(uint32_t *submitted,uint32_t *retired) '
    '__attribute__((weak_import));\n'
    'void note() { uint32_t submitted = 0, retired = 0; '
    'if(&native_adreno_fences && native_adreno_fences(&submitted,&retired)) {} }\n'
    'bool gpuWrote() { if(!&native_adreno_fences) return true; return false; }\n')

GLUE_FIXTURE = (
    'extern "C" {\n'
    'bool native_adreno_fences(uint32_t *submitted, uint32_t *retired) {\n'
    '    (void)submitted;\n'
    '    (void)retired;\n'
    '    return false;\n'
    '}\n'
    '}  // extern "C" (the board-provided fence query above)\n')

GLUE_PLAIN_FIXTURE = (
    'bool native_adreno_fences(uint32_t *submitted, uint32_t *retired) {\n'
    '    (void)submitted;\n'
    '    (void)retired;\n'
    '    return false;\n'
    '}\n')

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

FENCE_SIGNATURE = re.compile(
    r'bool\s+native_adreno_fences\s*\(\s*uint32_t\s*\*\s*submitted\s*,'
    r'\s*uint32_t\s*\*\s*retired\s*\)\s*\{')


def load_builder_pieces():
    tree = ast.parse(BUILDER.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in EXTRACT_NAMES:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in EXTRACT_NAMES for t in node.targets):
            nodes.append(node)
    namespace = {'re': re,
                 'require': lambda c, m: (_ for _ in ()).throw(AssertionError(m)) if not c else None}
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


def function_body(text, signature_match):
    """The brace-matched body following a signature match in `text`."""
    depth = 0
    i = signature_match.end() - 1
    start = i + 1
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    return text[start:i]


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
    fence_region = next((r for r in regions if '(the board-provided fence query above)' in r), '')
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

    check('glue has the marked fence-query extern "C" region', bool(fence_region),
          f'{len(regions)} extern "C" blocks found')
    fence_match = FENCE_SIGNATURE.search(fence_region)
    check('fence query defined with the exact component signature inside its region',
          fence_match is not None)
    fence_body = function_body(fence_region, fence_match) if fence_match else ''
    check('fence query returns false and never true',
          'return false;' in fence_body and 'return true' not in fence_body,
          f'body: {fence_body.strip()!r}')
    check('fence query is not defined inside the callback or probe regions',
          FENCE_SIGNATURE.search(callback_region) is None
          and FENCE_SIGNATURE.search(probe_region) is None)

    builder_text = BUILDER.read_text()
    check('builder carries no absent-binding mechanism (the Build #99 fixup source)',
          'optional_absent_bindings' not in builder_text and 'OPTIONAL_ABSENT' not in builder_text)

    ns = load_builder_pieces()
    decide = ns['board_provided_imports']
    weak = ns['N_WEAK_REF']
    name = '_native_adreno_fences'

    provided, violations = decide({name: weak}, COMPONENT_FIXTURE, GLUE_FIXTURE)
    check('weak import with a conforming glue definition is provided',
          provided == [name] and not violations, f'{provided} {violations}')

    provided, violations = decide({name: 0}, COMPONENT_FIXTURE, GLUE_FIXTURE)
    check('non-weak import is refused', provided == [] and len(violations) == 1)

    provided, violations = decide({}, COMPONENT_FIXTURE, GLUE_FIXTURE)
    check('unimported symbol needs no provider', provided == [] and not violations)

    provided, violations = decide({name: weak}, COMPONENT_FIXTURE.replace('__attribute__((weak_import))', ''), GLUE_FIXTURE)
    check('missing weak_import declaration is refused', provided == [] and len(violations) == 1)

    one_guard = COMPONENT_FIXTURE.replace('if(!&native_adreno_fences)', 'if(false)')
    provided, violations = decide({name: weak}, one_guard, GLUE_FIXTURE)
    check('a single address guard is refused', provided == [] and len(violations) == 1)

    provided, violations = decide({name: weak}, COMPONENT_FIXTURE, '')
    check('missing glue definition is refused', provided == [] and len(violations) == 1)

    provided, violations = decide({name: weak}, COMPONENT_FIXTURE, GLUE_PLAIN_FIXTURE)
    check('glue definition without C linkage is refused', provided == [] and len(violations) == 1)

    provided, violations = decide({name: weak}, COMPONENT_FIXTURE,
                                  GLUE_FIXTURE.replace('return false;', 'return true;'))
    check('a glue definition returning true is refused', provided == [] and len(violations) == 1)

    provided, violations = decide({name: weak}, COMPONENT_FIXTURE,
                                  GLUE_FIXTURE.replace('uint32_t *submitted', 'uint64_t *submitted'))
    check('a glue definition with the wrong signature is refused', provided == [] and len(violations) == 1)

    provided, violations = decide({'_native_ufs_dpu_map': weak}, COMPONENT_FIXTURE, GLUE_FIXTURE)
    check('non-allowlisted import is never provided', provided == [] and not violations)

    print('legacy linkage regression:', 'FAIL' if failures else 'PASS')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
