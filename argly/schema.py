from __future__ import annotations
from typing import Any
from copy import deepcopy
from argly._value_types import validate_metadata, validate_constraints

def _validate_spelling(name: str) -> None:
    if not isinstance(name, str) or '=' in name or any(char.isspace() for char in name):
        raise ValueError(f'invalid option spelling {name!r}')

    if name.startswith('--'):
        valid = len(name) > 2 and not name[2:].startswith(('-', '/'))
    elif name.startswith('-'):
        valid = len(name) == 2 and name[1].isascii() and name[1].isalpha()
    elif name.startswith('/'):
        valid = len(name) > 1 and '/' not in name[1:]
    else:
        valid = False

    if not valid:
        raise ValueError(f'invalid option spelling {name!r}')

def _validate_scalar(value: Any, spec: dict[str, Any], field: str) -> Any:
    kind = spec['type']
    dest = spec['dest']
    expected = {'str': str, 'int': int, 'float': float, 'bool': bool, 'path': str, 'uuid': str, 'date': str, 'datetime': str, 'enum': str, 'custom': str}[kind]
    if type(value) is not expected:
        raise ValueError(f'{dest}: {field} {value!r} does not match {kind}')

    if kind == 'float' and (value != value or value in (float('inf'), float('-inf'))):
        raise ValueError(f'{dest}: {field} must be finite')

    if kind in ('uuid', 'date', 'datetime') and isinstance(value, str):
        from argly._value_types import parse_extended

        parse_extended(value, spec)

    if kind in ('int', 'float'):
        validate_constraints(value, spec)

    if kind == 'path' and isinstance(value, str):
        from pathlib import Path

        return Path(value).as_posix()

    return value

def _validate_value(spec: dict[str, Any]) -> None:
    fields = ('dest', 'type', 'required', 'multiple', 'nullable', 'help', 'metavar', 'choices', 'default')
    if not isinstance(spec, dict) or any(field not in spec for field in fields):
        raise ValueError('value specification is missing required fields')

    dest = spec['dest']
    if not isinstance(dest, str) or not dest.isidentifier():
        raise ValueError(f'invalid parameter name {dest!r}')

    if spec['type'] not in ('str', 'int', 'float', 'bool', 'path', 'uuid', 'date', 'datetime', 'enum', 'custom'):
        raise ValueError(f'{dest}: unsupported type')

    for field in ('required', 'multiple', 'nullable'):
        if type(spec[field]) is not bool:
            raise ValueError(f'{dest}: {field} must be a bool')

    if not isinstance(spec['help'], str) or not isinstance(spec['metavar'], str):
        raise ValueError(f'{dest}: help and metavar must be strings')

    validate_metadata(spec)

    choices = spec['choices']
    if choices is not None and (not isinstance(choices, (list, tuple)) or not choices):
        raise ValueError(f'{dest}: choices must be nonempty')

    if choices is not None:
        choices = [_validate_scalar(choice, spec, 'choice') for choice in choices]
        spec['choices'] = choices

    default = spec['default']
    if spec['multiple']:
        if spec['nullable']:
            raise ValueError(f'{dest}: list values cannot be nullable')

        if not isinstance(default, (list, tuple)):
            raise ValueError(f'{dest}: a list value needs a list or tuple default')

        default = [_validate_scalar(item, spec, 'default') for item in default]
    elif default is None:
        if not spec['required'] and not spec['nullable']:
            raise ValueError(f'{dest}: default cannot be None unless nullable or required')
    else:
        default = _validate_scalar(default, spec, 'default')

    if choices is not None and default is not None:
        defaults = default if spec['multiple'] else [default]
        if any(item not in choices for item in defaults):
            raise ValueError(f'{dest}: default is outside the choices')

    spec['default'] = default

def validate_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Validate and detach a versioned registry before constructing parser tables."""
    data = deepcopy(registry)
    if data.get('version') != 1:
        raise ValueError('unsupported argly registry version')

    name = data.get('name')
    if not isinstance(name, str) or not name or any(char.isspace() for char in name):
        raise ValueError('application name must be a nonempty word')

    if type(data.get('windows_options')) is not bool:
        raise ValueError('windows_options must be a bool')

    commands = data.get('commands')
    if not isinstance(commands, list) or not commands:
        raise ValueError('registry must contain a root command')

    seen: dict[str, dict[str, Any]] = {}
    inherited: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in sorted(commands, key=lambda item: (item['path'].count(' '), item['path'])):
        path = entry['path']
        if not isinstance(path, str) or path != ' '.join(path.split()):
            raise ValueError('invalid command path')

        if any(part.startswith(('-', '/')) for part in path.split()):
            raise ValueError(f'invalid command path {path!r}')

        if path in seen:
            raise ValueError(f'duplicate command {path!r}')

        parent_path = path.rpartition(' ')[0]
        parent = seen.get(parent_path) if path else None
        if path and parent is None:
            raise ValueError(f'missing parent for {path!r}')

        if parent is not None and parent['arguments']:
            raise ValueError(
                f'commands with children cannot declare positional arguments: {parent_path!r}'
            )

        handler = entry['handler']
        if handler is not None and (not isinstance(handler, str) or ':' not in handler):
            raise ValueError(f'invalid handler reference for {path!r}')

        if type(entry.get('async', False)) is not bool:
            raise ValueError('async must be a bool')

        resources = entry.get('resources', {})
        if not isinstance(resources, dict) or any(
            not isinstance(parameter, str) or not parameter.isidentifier()
            or not isinstance(name, str) or not name.isidentifier()
            or parameter in entry['bindings']
            for parameter, name in resources.items()
        ):
            raise ValueError('resources must map unbound parameter names to resource names')

        if handler is None and (resources or entry.get('async')):
            raise ValueError('only command handlers can use resources or async execution')

        if not isinstance(entry['summary'], str):
            raise ValueError('command summary must be a string')

        scope = inherited[parent_path].copy() if path else {}
        spellings = {name for option in scope.values() for name in option['names']}
        spellings.update(('--help', '-h'))
        for option in entry['options']:
            _validate_value(option)
            dest = option['dest']
            if dest in scope:
                raise ValueError(f'{path!r}: option {dest!r} shadows an ancestor; use Inherited()')

            names = option['names']
            if not isinstance(names, (list, tuple)) or not names:
                raise ValueError(f'{dest}: an option needs at least one name')

            for spelling in names:
                _validate_spelling(spelling)
                if spelling in spellings:
                    raise ValueError(f'{path!r}: duplicate or reserved option {spelling!r}')

                spellings.add(spelling)

            action = option['action']
            if action not in ('value', 'flag', 'count'):
                raise ValueError(f'{dest}: unsupported action {action!r}')

            if action != 'value':
                expected = 'bool' if action == 'flag' else 'int'
                if option['type'] != expected or option['multiple'] or option['nullable']:
                    raise ValueError(f'{dest}: {action} requires {expected}')

                if option['required'] or option['choices'] is not None:
                    raise ValueError(f'{dest}: {action} cannot be required or have choices')
            elif option['type'] == 'bool':
                raise ValueError(f'{dest}: boolean options require the flag action')

            scope[dest] = option

        available = dict(scope)
        optional_seen = False
        arguments = entry['arguments']
        for index, argument in enumerate(arguments):
            _validate_value(argument)
            dest = argument['dest']
            if dest in available:
                raise ValueError(f'{path!r}: duplicate parameter {dest!r}')

            if argument['type'] == 'bool':
                raise ValueError('boolean positionals are unsupported; use Flag')

            if argument['multiple'] and index != len(arguments) - 1:
                raise ValueError('a variadic argument must be last')

            if optional_seen and argument['required']:
                raise ValueError('required arguments must precede optional arguments')

            optional_seen = not argument['required']
            available[dest] = argument

        for parameter, source in entry['bindings'].items():
            if (
                not isinstance(parameter, str)
                or not parameter.isidentifier()
                or source not in available
            ):
                raise ValueError(f'{path!r}: invalid parameter binding {parameter!r}')

        rules = entry.get('rules', [])
        if not isinstance(rules, list):
            raise ValueError('command rules must be a list')

        for rule in rules:
            if not isinstance(rule, dict) or rule.get('kind') not in ('exclusive', 'at_least_one', 'requires'):
                raise ValueError('invalid parameter relationship')

            parameters = rule.get('parameters')
            if not isinstance(parameters, list) or len(parameters) < (1 if rule['kind'] == 'at_least_one' else 2) or any(
                not isinstance(parameter, str) or parameter not in available for parameter in parameters
            ) or len(set(parameters)) != len(parameters):
                raise ValueError('relationship parameters must be distinct, declared names')

        inherited[path] = scope
        seen[path] = entry

    data['commands'] = list(seen.values())

    return data

def empty_command(path: str) -> dict[str, Any]:
    return {
        'path': path,
        'summary': '',
        'handler': None,
        'options': [],
        'arguments': [],
        'bindings': {},
    }
