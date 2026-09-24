"""Build prepared Python artifacts with separate runtime, help, and metadata.

Use argly gen --prepared --package PACKAGE --name NAME --output generated.py.
Call generated.main() from the console entry point, or generated.load() to
construct an app. Ship generated.py and its sibling
_generated_* modules together. --check verifies every artifact without writing.
"""
from __future__ import annotations
from enum import Enum
from typing import Any
from pathlib import Path
from argly.app import App
from hashlib import sha256
from collections.abc import Mapping
from argly._references import resolve
from argly._generated import FORMAT_VERSION

class _Code(str):
    """An expression produced by the generator, never declaration text."""

def _literal(value: Any) -> str:
    if isinstance(value, _Code):
        return str(value)

    if isinstance(value, Mapping):
        return 'M({' + ', '.join(f'{key!r}: {_literal(item)}' for key, item in value.items()) + '})'

    if isinstance(value, (list, tuple)):
        return '(' + ''.join(_literal(item) + ', ' for item in value) + ')'

    return repr(value)

def _bounds_source(spec: Mapping[str, Any], result: str, original: str) -> list[str]:
    lines: list[str] = []
    for field, comparison, label in (('minimum', '>=', 'at least'), ('maximum', '<=', 'at most')):
        bound = spec.get('constraints', {}).get(field)
        if bound is not None:
            message = f'{spec["dest"]}: must be {label} {bound}'
            lines.extend((
                f'    if not {result} {comparison} {bound!r}:',
                f'        raise UsageError({message!r}, code=\'constraint\', parameter={spec["dest"]!r}, value={original})',
            ))

    return lines

def _conversion_source(spec: Mapping[str, Any], symbol: str) -> list[str]:
    kind = spec['type']
    dest = spec['dest']
    choices = spec['choices']
    lines = [f'def {symbol}(value, _spec):']
    if kind == 'str' and choices is None:
        return [*lines, '    return value', '']

    choice_tokens = tuple(map(str, choices)) if choices is not None else ()
    choice_message = f'{dest}: choose from ' + ', '.join(choice_tokens)
    suggestion_value = 'result.as_posix()' if kind == 'path' else 'value'
    choice_error = f'raise UsageError({choice_message!r}, code=\'invalid_choice\', parameter={dest!r}, value=value, suggestions=_suggest({suggestion_value}, {choice_tokens!r}))'
    if kind == 'enum':
        lines.extend((f'    if value not in {tuple(choices)!r}:', '        ' + choice_error))

    lines.append('    try:')
    if kind in ('str', 'int', 'float'):
        expression = 'value' if kind == 'str' else f'{kind}(value)'
        lines.append(f'        result = {expression}')
    elif kind == 'path':
        lines.extend(('        from pathlib import Path', '', '        result = Path(value)'))
    elif kind == 'uuid':
        lines.extend(('        from uuid import UUID', '', '        result = UUID(value)'))
    elif kind in ('date', 'datetime'):
        lines.extend((f'        from datetime import {kind}', '', f'        result = {kind}.fromisoformat(value)'))
    else:
        lines.extend(('        from argly._references import resolve', ''))
        if kind == 'enum':
            lines.append(f'        result = resolve({spec["enum"]!r})[{dict(spec["enum_members"])!r}[value]]')
        else:
            lines.append(f'        result = resolve({spec["converter"]!r})(value)')

    lines.extend((
        '    except (ValueError, OverflowError, TypeError) as error:',
        f'        raise UsageError({(dest + ": invalid " + kind + " value ")!r} + repr(value), code=\'invalid_value\', parameter={dest!r}, value=value) from error', '',
    ))
    if choices is not None and kind != 'enum':
        choice = 'result' if kind in ('str', 'int', 'float') else 'result.as_posix()' if kind == 'path' else 'value'
        lines.extend((f'    if {choice} not in {tuple(choices)!r}:', '        ' + choice_error, ''))

    lines.extend(_bounds_source(spec, 'result', 'value'))
    if spec.get('constraints', {}).get('path') is not None:
        lines.extend((
            '    from argly._value_types import validate_constraints', '',
            '    try:', '        validate_constraints(result, _spec)',
            '    except ValueError as error:',
            f'        raise UsageError({(dest + ": ")!r} + str(error), code=\'constraint\', parameter={dest!r}, value=value) from error',
        ))

    lines.extend(('    return result', ''))

    return lines

def _rules_source(rules: Any, symbol: str) -> list[str]:
    parameters = dict.fromkeys(parameter for rule in rules for parameter in rule['parameters'])
    bits = {parameter: 1 << index for index, parameter in enumerate(parameters)}
    lines = [f'def {symbol}(supplied, _bits={_literal(bits)}):', '    mask = 0', '    for parameter in supplied:', '        mask |= _bits.get(parameter, 0)', '']
    for rule in rules:
        names = rule['parameters']
        mask = sum(bits[name] for name in names)
        parameter = None
        if rule['kind'] == 'exclusive':
            condition = f'(mask & {mask}).bit_count() > 1'
            message = 'mutually exclusive parameters: ' + ', '.join(names)
            code = 'conflicting_parameters'
        elif rule['kind'] == 'at_least_one':
            condition = f'not mask & {mask}'
            message = 'supply at least one of: ' + ', '.join(names)
            code = 'missing_selection'
        else:
            condition = f'mask & {bits[names[0]]} and mask & {mask} != {mask}'
            message = names[0] + ' requires: ' + ', '.join(names[1:])
            code = 'missing_dependency'
            parameter = names[0]

        lines.extend((f'    if {condition}:', f'        raise UsageError({message!r}, code={code!r}, parameter={parameter!r})', ''))

    return lines

def _runtime_source(app: App) -> str:
    # The app passed here has freshly validated metadata and compiled nodes.
    # noinspection PyProtectedMember
    nodes = app._nodes
    specs: dict[str, _Code] = {}
    lines = [
        'from types import MappingProxyType as M',
        'from argly._parser import _suggest, UsageError', '',
        f'FORMAT_VERSION = {FORMAT_VERSION}', f'NAME = {app.name!r}',
        f'WINDOWS_OPTIONS = {app.registry["windows_options"]!r}', '',
    ]

    def parameter(spec: Mapping[str, Any]) -> _Code:
        compact = {key: value for key, value in spec.items() if key not in ('help', 'metavar', 'names')}
        default = compact['default']
        if compact['type'] == 'path' and default is not None:
            compact['default'] = [Path(item).as_posix() for item in default] if compact['multiple'] else Path(default).as_posix()

        text = _literal(compact)
        if text not in specs:
            index = len(specs)
            symbol = _Code(f'_s{index}')
            specs[text] = symbol
            if compact.get('action', 'value') == 'value':
                converter = _Code(f'_convert{index}')
                lines.extend(_conversion_source(compact, converter))
                compact['_convert'] = converter

            if compact['type'] in ('int', 'float') and compact.get('constraints'):
                validator = _Code(f'_validate{index}')
                lines.extend((f'def {validator}(value):', '    if value is None:', '        return value', ''))
                lines.extend(_bounds_source(compact, 'value', 'str(value)'))
                lines.extend(('    return value', ''))
                compact['_validate'] = validator

            lines.extend((f'{symbol} = {_literal(compact)}', ''))

        return specs[text]

    commands = {}
    bindings: dict[str, _Code] = {}
    rules: dict[str, _Code] = {}
    for path, node in nodes.items():
        options = tuple(parameter(spec) for spec in node.options)
        arguments = tuple(parameter(spec) for spec in node.arguments)
        lookup = {name: parameter(spec) for name, spec in node.lookup.items()}
        defaults = {spec['dest']: spec['default'] for spec in node.options}
        checked = tuple(parameter(spec) for spec in node.options if spec['type'] in ('path', 'uuid', 'date', 'datetime', 'enum', 'custom') or spec.get('constraints'))
        binding_key = repr(tuple(node.bindings.items()))
        if binding_key not in bindings:
            binder = _Code(f'_bind{len(bindings)}')
            bindings[binding_key] = binder
            expression = ', '.join(f'{name!r}: values[{source!r}]' for name, source in node.bindings.items())
            lines.extend((f'def {binder}(values):', '    return {' + expression + '}', ''))

        rule_key = _literal(node.rules)
        if node.rules and rule_key not in rules:
            validator = _Code(f'_rules{len(rules)}')
            rules[rule_key] = validator
            lines.extend(_rules_source(node.rules, validator))

        commands[path] = (
            node.handler, node.is_async, node.bindings, options, arguments,
            lookup, defaults, node.required, node.mutable_defaults, checked,
            node.rules, node.resources, {name: child.path for name, child in node.children.items()},
            bindings[binding_key], rules.get(rule_key),
        )

    lines.extend(('', 'COMMANDS = ' + _literal(commands), ''))

    return '\n'.join(lines)

def _entry_source(runtime: str, help_module: str, metadata: str) -> str:
    return f'''"""Generated argly entry point. Ship its sibling modules with this file."""
from importlib import import_module as _import_module

def _module(name):
    return _import_module('.' + name, __package__) if __package__ else _import_module(name)

def get_help(path):
    return _module({help_module!r}).HELP.get(path)

def get_registry():
    return _module({metadata!r}).get_registry()

def load(*, resources=None):
    from argly import App

    return App.from_generated(_module({runtime!r}), help_lookup=get_help, registry_loader=get_registry, resources=resources)

def main(args=None, *, out=None, err=None, resources=None):
    from sys import argv, stdout

    arguments = list(argv[1:] if args is None else args)
    if arguments and arguments[-1] in ('--help', '-h'):
        tokens = arguments[:-1]
        path = ' '.join(tokens)
        if path.split() == tokens:
            text = get_help(path)
            if text is not None:
                (stdout if out is None else out).write(text)
                return 0

    return load(resources=resources).run(arguments, out=out, err=err)

if __name__ == '__main__':
    raise SystemExit(main())
'''

def validate_references(registry: dict[str, Any]) -> None:
    """Resolve references at build time without invoking handlers or converters."""
    checked: set[tuple[str, str]] = set()
    for entry in registry['commands']:
        references = [('handler', entry['handler'])] if entry['handler'] else []
        for spec in (*entry['options'], *entry['arguments']):
            references.extend((kind, spec[kind]) for kind in ('converter', 'enum') if kind in spec)

        for kind, reference in references:
            if (kind, reference) in checked:
                continue

            if '<locals>' in reference or reference.startswith('__main__:'):
                raise ValueError(f'generated {kind}s must be importable module-level functions or types')

            try:
                target = resolve(reference)
            except (ValueError, ImportError, AttributeError) as error:
                raise ValueError(f'cannot import {kind} {reference!r}') from error

            if kind == 'enum':
                if not isinstance(target, type) or not issubclass(target, Enum):
                    raise ValueError(f'{reference!r} must refer to an enum type')
            elif not callable(target):
                raise ValueError(f'{kind} {reference!r} must be callable')

            checked.add((kind, reference))

        for spec in (*entry['options'], *entry['arguments']):
            if spec['type'] == 'enum':
                enum_type = resolve(spec['enum'])
                if any(name not in enum_type.__members__ or str(enum_type[name].value) != value for value, name in spec['enum_members'].items()):
                    raise ValueError(f'{spec["enum"]!r} members have changed; rediscover the declarations')

def artifacts(app: App, output: Path) -> dict[Path, str]:
    """Compile deterministic sibling modules; metadata stays out of execution."""
    from pprint import pformat
    from argly.helpgen import render

    if output.suffix != '.py' or not output.stem.isidentifier():
        raise ValueError('prepared output must be a .py module with an identifier name')

    app = App.from_registry(app.registry)
    validate_references(app.registry)
    runtime = _runtime_source(app)
    # Preserve declaration order, including resource acquisition and cleanup.
    metadata = 'def get_registry():\n    return ' + pformat(app.registry, width=100, sort_dicts=False).replace('\n', '\n    ') + '\n'
    # noinspection PyProtectedMember
    help_source = 'HELP = ' + repr({path: render(app.name, node) for path, node in app._nodes.items()}) + '\n'
    fingerprint = sha256((runtime + '\0' + help_source + '\0' + metadata).encode()).hexdigest()[:20]
    prefix = '_' + output.stem + '_' + fingerprint
    names = [prefix + suffix for suffix in ('_runtime', '_help', '_metadata')]
    result = {output.with_name(name + '.py'): data for name, data in zip(names, (runtime, help_source, metadata), strict=True)}
    result[output] = _entry_source(*names)
    for path, text in result.items():
        compile(text, path.name, 'exec')

    return result

def generate(app: App, output: Path, *, check: bool = False) -> bool:
    """Publish dependencies first and switch the entry point atomically last.

    Content-addressed siblings prevent readers from mixing generations. Older
    siblings may still be in use; remove them only when packaging a fresh build.
    """
    from argly.helpgen import write_output

    generated = artifacts(app, output)
    results = [write_output(path, text.encode(), check=check) for path, text in generated.items()]

    return all(results)
