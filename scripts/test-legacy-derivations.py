#!/usr/bin/env python3
"""Regression test for the legacy display builder's systematic bindings
derivation (derive_missing_bindings in build-fuxi-legacy-display.py).

Builds #93/#94 failed Gate 3 one slot at a time (21 init, then 44
setProperties) because the E2 record's bindings map names only the
symbols its audit qualified directly, while the record's method table
carries all 358 original addresses. The builder now derives the missing
bindings from that method table in accounted forms only. This test
extracts the derivation from the builder source and checks, against the
real record and a synthetic compiled vtable built to the audit's slot
classification:

  1. the full expected set is derived (named slots, the 79/85/111
     group, all opaque slots, the qualified-base-call twins), each at
     the record's method-table address, with no violations;
  2. an opaque symbol at the wrong slot is not derived;
  3. a named symbol at the wrong slot is not derived;
  4. a group symbol outside slots 79/85/111 is not derived;
  5. a record standalone field disagreeing with the method table
     refuses the twin derivation for that slot;
  6. a conflicting pre-existing binding is refused, not overwritten;
  7. an ambiguous twin (two component overrides mapping to one
     original symbol) is not derived;
  8. an unaccounted original-class symbol is not derived.

Run: python3 scripts/test-legacy-derivations.py (exit 0 = pass).
"""
import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / 'build-fuxi-legacy-display.py'
RECORD = HERE / 'fuxi-21H461-mobile-graphics-legacy-abi.json'

LEGACY = '25IOMobileFramebufferLegacy'
NATIVE = '19NativeLegacyDisplay'
INIT = f'__ZN{LEGACY}4initEP12OSDictionary'
SET_PROPERTIES = f'__ZN{LEGACY}13setPropertiesEP8OSObject'
SYSTEM_WILL_SHUTDOWN = f'__ZN{LEGACY}18systemWillShutdownEj'
PROBE = f'__ZN{LEGACY}5probeEP9IOServicePi'
GET_WORK_LOOP = f'__ZNK{LEGACY}11getWorkLoopEv'
GET_DISPLAY_DIMENSIONS = f'__ZN{LEGACY}20getDisplayDimensionsEPjS0_'
COMPLETE_CURRENT_SWAP = f'__ZN{LEGACY}19completeCurrentSwapEv'
APPLY_STATE_REQUEST = f'__ZN{LEGACY}17applyStateRequestEP26OriginalLegacyStateRequestb'
FREE = f'__ZN{LEGACY}4freeEv'
SET_POWER_STATE = f'__ZN{LEGACY}13setPowerStateEmP9IOService'
START = f'__ZN{LEGACY}5startEP9IOService'
STOP = f'__ZN{LEGACY}4stopEP9IOService'
NEW_USER_CLIENT = f'__ZN{LEGACY}13newUserClientEP4taskPvjPP12IOUserClient'
GET_REFRESH_ATTRIBUTES = f'__ZN{LEGACY}20getRefreshAttributesEPyb'

EXTRACT_NAMES = {'NAMED_SLOT_BINDINGS', 'NAMED_SLOT_GROUP', 'STANDALONE_FIELDS',
                 'LEGACY_INIT_SYMBOL', 'opaque_symbol', 'derive_missing_bindings',
                 'apply_original_init_alias'}


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


def base_bindings(audit):
    return {name: int(value, 16) for name, value in audit['bindings'].items()
            if isinstance(value, str) and value.startswith('0x')}


def synthetic_compiled(audit):
    """A compiled vtable matching the audit's slot classification: the
    component's own overrides at the owned slots (with the exact
    manglings of the methods it calls back into the base class for),
    pure-virtual markers at the abstract slots, original-class symbols
    at the inherited named slots, opaque{i} elsewhere >= 168, and
    inherited native-base symbols below 168."""
    pure = set(audit['abstract_slots'])
    native_twins = {
        7: f'__ZN{NATIVE}4freeEv',
        14: f'__ZN{NATIVE}13setPowerStateEmP9IOService',
        86: f'__ZN{NATIVE}5startEP9IOService',
        87: f'__ZN{NATIVE}4stopEP9IOService',
        141: f'__ZN{NATIVE}13newUserClientEP4taskPvjPP12IOUserClient',
        301: f'__ZN{NATIVE}20getRefreshAttributesEPyb',
    }
    owned = (0, 1, 7, 14, 84, 86, 87, 141, 155, 184, 188, 288, 290, 296, 301)
    legacy_named = {21: INIT, 44: SET_PROPERTIES, 79: SYSTEM_WILL_SHUTDOWN,
                    85: PROBE, 111: GET_WORK_LOOP, 249: GET_DISPLAY_DIMENSIONS,
                    295: COMPLETE_CURRENT_SWAP, 354: APPLY_STATE_REQUEST}
    compiled = []
    for i in range(358):
        if i in native_twins:
            compiled.append(native_twins[i])
        elif i in owned:
            compiled.append(f'__ZN{NATIVE}9owned{i}Ev')
        elif i in pure:
            compiled.append('___cxa_pure_virtual')
        elif i in legacy_named:
            compiled.append(legacy_named[i])
        elif i >= 168:
            compiled.append(f'__ZN{LEGACY}9opaque{i}Ev')
        else:
            compiled.append('__ZN9IOService15registerServiceEv')
    return compiled


def synthetic_undefined(audit, compiled):
    undefined = set(base_bindings(audit)) | {INIT, FREE, SET_POWER_STATE, START,
                                             STOP, NEW_USER_CLIENT, GET_REFRESH_ATTRIBUTES}
    undefined |= {n for n in compiled if LEGACY in n}
    return undefined


def main():
    pieces = load_builder_pieces()
    derive = pieces['derive_missing_bindings']
    audit = json.loads(RECORD.read_text())
    methods = audit['methods']
    failures = []

    def check(name, condition, detail=''):
        if not condition:
            failures.append(f'{name}: {detail}')

    def run(audit_in, compiled, undefined, alias=True):
        bindings = base_bindings(audit_in)
        if alias:
            bindings = pieces['apply_original_init_alias'](bindings, audit_in)
        return derive(bindings, audit_in, compiled, undefined), bindings

    # 1. The full expected derivation on the real record.
    compiled = synthetic_compiled(audit)
    undefined = synthetic_undefined(audit, compiled)
    (derived, violations), bindings = run(audit, compiled, undefined)
    check('full derivation', not violations, f'violations: {violations}')
    check('full derivation', len(derived) == 185,
          f'derived {len(derived)} bindings, expected 185 '
          '(1 setProperties + 3 group + 3 named + 172 opaque + 6 twins)')
    for name, entry in derived.items():
        check('full derivation',
              bindings[name] == int(methods[entry['slot']]['address'], 16),
              f'{name} not at the record address for slot {entry["slot"]}')
    for name in (SET_PROPERTIES, SYSTEM_WILL_SHUTDOWN, PROBE, GET_WORK_LOOP,
                 GET_DISPLAY_DIMENSIONS, COMPLETE_CURRENT_SWAP, APPLY_STATE_REQUEST,
                 FREE, SET_POWER_STATE, START, STOP, NEW_USER_CLIENT, GET_REFRESH_ATTRIBUTES):
        check('full derivation', name in derived, f'{name} not derived')

    # 2. An opaque symbol at the wrong slot is not derived.
    compiled2 = list(compiled)
    compiled2[199] = '__ZN9IOService15registerServiceEv'
    compiled2[200] = f'__ZN{LEGACY}9opaque199Ev'
    (derived2, _), bindings2 = run(audit, compiled2, synthetic_undefined(audit, compiled2))
    check('opaque wrong slot', f'__ZN{LEGACY}9opaque199Ev' not in bindings2,
          'opaque199 derived at slot 200')

    # 3. A named symbol at the wrong slot is not derived.
    compiled3 = list(compiled)
    compiled3[44] = '__ZN9IOService15registerServiceEv'
    compiled3[45] = SET_PROPERTIES
    (derived3, _), bindings3 = run(audit, compiled3, synthetic_undefined(audit, compiled3))
    check('named wrong slot', SET_PROPERTIES not in bindings3,
          'setProperties derived at slot 45')

    # 4. A group symbol outside slots 79/85/111 is not derived.
    compiled4 = list(compiled)
    compiled4[85] = '__ZN9IOService15registerServiceEv'
    compiled4[100] = PROBE
    (derived4, _), bindings4 = run(audit, compiled4, synthetic_undefined(audit, compiled4))
    check('group outside set', PROBE not in bindings4, 'probe derived at slot 100')

    # 5. A standalone field disagreeing with the method table refuses the twin.
    mutated = json.loads(RECORD.read_text())
    mutated['original_start'] = '0xfffffff000000000'
    (derived5, violations5), bindings5 = run(mutated, compiled, undefined)
    check('standalone mismatch', START not in bindings5, 'start derived despite field mismatch')
    check('standalone mismatch', any('original_start' in v for v in violations5),
          f'no original_start violation reported: {violations5}')

    # 6. A conflicting pre-existing binding is refused, not overwritten.
    bindings6 = pieces['apply_original_init_alias'](base_bindings(audit), audit)
    bindings6[SET_PROPERTIES] = 0x1000
    derived6, violations6 = derive(bindings6, audit, compiled, undefined)
    check('conflicting binding', bindings6[SET_PROPERTIES] == 0x1000,
          'conflicting binding overwritten')
    check('conflicting binding', any('conflicts' in v for v in violations6),
          f'no conflict violation reported: {violations6}')

    # 7. An ambiguous twin is not derived.
    compiled7 = list(compiled)
    compiled7[155] = f'__ZN{NATIVE}4freeEv'
    (derived7, _), bindings7 = run(audit, compiled7, synthetic_undefined(audit, compiled7))
    check('ambiguous twin', FREE not in bindings7, 'free derived from an ambiguous twin')

    # 8. An unaccounted original-class symbol is not derived.
    compiled8 = list(compiled)
    compiled8[50] = f'__ZN{LEGACY}7unknownEv'
    undefined8 = synthetic_undefined(audit, compiled8)
    (derived8, violations8), bindings8 = run(audit, compiled8, undefined8)
    check('unaccounted symbol', f'__ZN{LEGACY}7unknownEv' not in bindings8,
          'unknown symbol derived')

    if failures:
        for failure in failures:
            print(f'FAIL: {failure}')
        return 1
    print('PASS: systematic bindings derivation regression (8 cases)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
