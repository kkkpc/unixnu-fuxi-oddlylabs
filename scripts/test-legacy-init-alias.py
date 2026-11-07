#!/usr/bin/env python3
"""Regression test for the legacy display builder's slot-21 init alias.

The E2 ABI record carries the original IOMobileFramebufferLegacy init
address in its top-level original_init field and in methods[21], but not
in bindings; build-fuxi-legacy-display.py maps it explicitly via
apply_original_init_alias(). This test extracts that function from the
builder source and checks, against the real record:

  1. the real record gains exactly the init binding at the record address;
  2. an original_init that disagrees with methods[21] is refused;
  3. a methods[21] entry whose slot is not 21 is refused;
  4. a pre-existing conflicting init binding is refused.

Run: python3 scripts/test-legacy-init-alias.py (exit 0 = pass).
"""
import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / 'build-fuxi-legacy-display.py'
RECORD = HERE / 'fuxi-21H461-mobile-graphics-legacy-abi.json'
INIT_SYMBOL = '__ZN25IOMobileFramebufferLegacy4initEP12OSDictionary'


class Refused(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def load_alias_function():
    tree = ast.parse(BUILDER.read_text())
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name == 'apply_original_init_alias')
             or (isinstance(n, ast.Assign) and any(
                 isinstance(t, ast.Name) and t.id == 'LEGACY_INIT_SYMBOL' for t in n.targets))]
    if len(nodes) != 2:
        raise SystemExit('could not extract apply_original_init_alias from the builder')
    namespace = {'require': require}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BUILDER), 'exec'), namespace)
    return namespace['apply_original_init_alias']


def base_bindings(audit):
    return {name: int(value, 16) for name, value in audit['bindings'].items()
            if isinstance(value, str) and value.startswith('0x')}


def main():
    apply_alias = load_alias_function()
    audit = json.loads(RECORD.read_text())
    failures = []

    def case(name, fn, should_pass):
        try:
            fn()
        except Refused:
            if should_pass:
                failures.append(f'{name}: refused but should pass')
            return
        if not should_pass:
            failures.append(f'{name}: passed but should be refused')

    # 1. The real record passes and gains exactly one binding.
    def good():
        bindings = apply_alias(base_bindings(audit), audit)
        expected = int(audit['original_init'], 16)
        require(bindings[INIT_SYMBOL] == expected, 'alias address mismatch')
        require(len(bindings) == len(base_bindings(audit)) + 1, 'binding count drift')
    case('real record', good, True)

    # 2. original_init disagreeing with methods[21] is refused.
    def bad_field():
        mutated = json.loads(RECORD.read_text())
        mutated['original_init'] = '0xfffffff000000000'
        apply_alias(base_bindings(mutated), mutated)
    case('original_init mismatch', bad_field, False)

    # 3. A methods[21] entry that is not slot 21 is refused.
    def bad_slot():
        mutated = json.loads(RECORD.read_text())
        mutated['methods'][21]['slot'] = 22
        apply_alias(base_bindings(mutated), mutated)
    case('slot identity mismatch', bad_slot, False)

    # 4. A conflicting pre-existing init binding is refused.
    def conflict():
        bindings = base_bindings(audit)
        bindings[INIT_SYMBOL] = 0x1000
        apply_alias(bindings, audit)
    case('conflicting binding', conflict, False)

    if failures:
        for failure in failures:
            print(f'FAIL: {failure}')
        return 1
    print('PASS: slot-21 init alias regression (4 cases)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
