from __future__ import annotations
from typing import Any
from collections.abc import Mapping, Iterable, Sequence

class UsageError(ValueError):
    """A usage failure with stable fields, reported by App.run with exit status 2.

    code identifies the failure independently of human wording. command is the
    command path, parameter the declaration name (or unknown option spelling),
    and value the offending input when available. suggestions never change input.
    """

    def __init__(self, message: str, *, code: str = 'usage_error', command: str = '', parameter: str | None = None, value: str | None = None, suggestions: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.command = command
        self.parameter = parameter
        self.value = value
        self.suggestions = tuple(suggestions)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible diagnostics without relying on message parsing."""
        return {'code': self.code, 'message': str(self), 'command': self.command, 'parameter': self.parameter, 'value': self.value, 'suggestions': list(self.suggestions)}

class ParseResult:
    __slots__ = ('node', 'values', 'help_requested')

    def __init__(self, node: Node, values: dict[str, Any], help_requested: bool) -> None:
        self.node = node
        self.values = values
        self.help_requested = help_requested

class Node:
    __slots__ = (
        'path',
        'summary',
        'handler',
        'bindings',
        'options',
        'arguments',
        'children',
        'lookup',
        'defaults',
        'required',
        'mutable_defaults',
        'windows_options',
        'rules',
        'checked_defaults',
        'is_async',
        'resources',
    )

    def __init__(self, data: dict[str, Any], parent: Node | None, windows: bool) -> None:
        self.path: str = data['path']
        self.summary: str = data['summary']
        self.handler: str | None = data['handler']
        self.is_async: bool = data.get('async', False)
        self.resources: tuple[tuple[str, str], ...] = tuple(data.get('resources', {}).items())
        self.bindings: Mapping[str, str] = data['bindings']
        self.arguments: Sequence[Mapping[str, Any]] = [spec.copy() for spec in data['arguments']]
        self.children: Mapping[str, Node] = {}
        self.windows_options = windows
        self.rules: Sequence[Mapping[str, Any]] = ([] if parent is None else list(parent.rules)) + data.get('rules', [])
        self.options: Sequence[Mapping[str, Any]] = ([] if parent is None else list(parent.options)) + data[
            'options'
        ]
        lookup: dict[str, Mapping[str, Any]] = {}
        self.lookup: Mapping[str, Mapping[str, Any]] = lookup
        self.defaults: dict[str, Any] = {}
        self.required: list[str] = []
        for option in self.options:
            for spelling in option['names']:
                if windows or not spelling.startswith('/'):
                    lookup[spelling] = option

            self.defaults[option['dest']] = _default_value(option)
            if option['required']:
                self.required.append(option['dest'])

        for argument in self.arguments:
            assert isinstance(argument, dict)
            argument['default'] = _default_value(argument)

        self.mutable_defaults = tuple(
            dest for dest, default in self.defaults.items() if isinstance(default, list)
        )
        self.checked_defaults = tuple(spec for spec in self.options if spec['type'] in ('uuid', 'date', 'datetime', 'enum', 'custom') or spec.get('constraints'))

    def add_child(self, name: str, node: Node) -> None:
        assert isinstance(self.children, dict)
        self.children[name] = node

def _default_value(spec: Mapping[str, Any], *, check: bool = False) -> Any:
    default = spec['default']
    if check and default is not None:
        if spec['multiple']:
            return [_checked_default(item, spec) for item in default]

        return _checked_default(default, spec)

    if default is not None and spec['type'] == 'path':
        if spec['multiple']:
            return [_convert(item, spec, check=False) for item in default]

        return _convert(default, spec, check=False)

    return default

def _checked_default(value: Any, spec: Mapping[str, Any]) -> Any:
    if spec['type'] in ('path', 'uuid', 'date', 'datetime', 'enum', 'custom'):
        return _convert(str(value), spec)

    if spec.get('constraints'):
        from argly._value_types import validate_constraints

        try:
            validate_constraints(value, spec)
        except ValueError as error:
            raise UsageError(f'{spec["dest"]}: {error}', code='constraint', parameter=spec['dest'], value=str(value)) from error

    return value

def _convert(value: str, spec: Mapping[str, Any], *, check: bool = True) -> Any:
    original = value
    kind = spec['type']
    if kind == 'enum' and value not in spec['choices']:
        raise UsageError(f'{spec["dest"]}: choose from {", ".join(spec["choices"])}', code='invalid_choice', parameter=spec['dest'], value=value, suggestions=_suggest(value, spec['choices']))

    try:
        if kind == 'str':
            result: Any = value
        elif kind == 'int':
            result = int(value)
        elif kind == 'float':
            result = float(value)
        elif kind == 'path':
            from pathlib import Path

            path = Path(value)
            result = path
            value = path.as_posix()
        else:
            from argly._value_types import parse_extended

            result = parse_extended(value, spec)
    except (ValueError, OverflowError, TypeError) as error:
        raise UsageError(f'{spec["dest"]}: invalid {kind} value {original!r}', code='invalid_value', parameter=spec['dest'], value=original) from error

    choices = spec['choices']
    choice_value = value if kind in ('path', 'uuid', 'date', 'datetime', 'enum', 'custom') else result
    if choices is not None and choice_value not in choices:
        raise UsageError(f'{spec["dest"]}: choose from {", ".join(map(str, choices))}', code='invalid_choice', parameter=spec['dest'], value=original, suggestions=_suggest(value, map(str, choices)))

    if check and spec.get('constraints'):
        from argly._value_types import validate_constraints

        try:
            validate_constraints(result, spec)
        except ValueError as error:
            raise UsageError(f'{spec["dest"]}: {error}', code='constraint', parameter=spec['dest'], value=original) from error

    return result

def _store(values: dict[str, Any], spec: Mapping[str, Any], value: str | None) -> None:
    dest = spec['dest']
    action = spec['action']
    if action == 'flag':
        values[dest] = not spec['default']
    elif action == 'count':
        values[dest] = values.get(dest, spec['default']) + 1
    else:
        assert value is not None
        converted = _convert(value, spec)
        if spec['multiple']:
            if dest in values:
                values[dest].append(converted)
            else:
                values[dest] = [converted]
        else:
            values[dest] = converted

def _looks_like_option(value: str, node: Node) -> bool:
    if value == '--' or value in ('--help', '-h'):
        return True

    if value.startswith('-') and value != '-':
        try:
            float(value)
        except ValueError:
            return True

    return node.windows_options and value.partition('=')[0] in node.lookup

def _suggest(value: str, choices: Iterable[str]) -> tuple[str, ...]:
    from difflib import get_close_matches

    return tuple(get_close_matches(value, choices, n=3, cutoff=0.6))

def parse(root: Node, argv: list[str]) -> ParseResult:
    node = root
    values: dict[str, Any] = {}
    positionals: list[str] = []
    help_requested = False
    literal = False
    index = 0
    size = len(argv)
    try:
        while index < size:
            token = argv[index]
            index += 1
            if literal:
                positionals.append(token)
                continue

            if token == '--':
                literal = True
                continue

            if token in ('--help', '-h'):
                help_requested = True
                continue

            name, equal, attached = token.partition('=')
            spec = node.lookup.get(name)
            if spec is not None:
                if spec['action'] != 'value':
                    if equal:
                        raise UsageError(f'{name} does not take a value', code='unexpected_value', parameter=spec['dest'], value=attached)

                    _store(values, spec, None)
                    continue

                if not equal:
                    if index == size or _looks_like_option(argv[index], node):
                        raise UsageError(
                            f"{name} requires a value (use {name}=VALUE for a value starting with '-')",
                            code='missing_value', parameter=spec['dest'],
                        )

                    attached = argv[index]
                    index += 1

                _store(values, spec, attached)
                continue

            if token.startswith('--'):
                raise UsageError(f'unknown option {name!r}', code='unknown_option', parameter=name, value=token, suggestions=_suggest(name, node.lookup))

            negative_number = False
            if (
                token.startswith('-')
                and len(token) > 1
                and (token[1].isdigit() or token[1] == '.')
                and node.arguments
            ):
                try:
                    float(token)
                    negative_number = True
                except ValueError:
                    pass

            if token.startswith('-') and token != '-' and not negative_number:
                offset = 1
                while offset < len(token):
                    short = '-' + token[offset]
                    if short == '-h':
                        help_requested = True
                        offset += 1
                        continue

                    spec = node.lookup.get(short)
                    if spec is None:
                        raise UsageError(f'unknown option {short!r}', code='unknown_option', parameter=short, value=token, suggestions=_suggest(short, node.lookup))

                    offset += 1
                    if spec['action'] != 'value':
                        _store(values, spec, None)
                        continue

                    attached = token[offset:]
                    if attached.startswith('='):
                        attached = attached[1:]
                    elif not attached:
                        if index == size or _looks_like_option(argv[index], node):
                            raise UsageError(f'{short} requires a value', code='missing_value', parameter=spec['dest'])

                        attached = argv[index]
                        index += 1

                    _store(values, spec, attached)
                    break

                continue

            if node.children and not positionals:
                child = node.children.get(token)
                if child is None:
                    raise UsageError(f'unknown command {token!r} under {node.path or "<root>"}', code='unknown_command', value=token, suggestions=_suggest(token, node.children))

                node = child
                continue

            positionals.append(token)

        if help_requested:
            return ParseResult(node, values, True)

        for dest in node.required:
            if dest not in values:
                raise UsageError(f'missing required option --{dest.replace("_", "-")}', code='missing_option', parameter=dest)

        result = node.defaults.copy()
        for dest in node.mutable_defaults:
            if dest not in values:
                result[dest] = list(result[dest])

        result.update(values)
        supplied = set(values)
        for spec in node.checked_defaults:
            if spec['dest'] not in values:
                result[spec['dest']] = _default_value(spec, check=True)
            elif spec['action'] == 'count':
                _checked_default(result[spec['dest']], spec)

        offset = 0
        for spec in node.arguments:
            dest = spec['dest']
            if spec['multiple']:
                rest = positionals[offset:]
                if spec['required'] and not rest:
                    raise UsageError(f'missing required argument {dest}', code='missing_argument', parameter=dest)

                result[dest] = [_convert(value, spec) for value in rest] if rest else _default_value(spec, check=True)[:]
                if rest:
                    supplied.add(dest)
                offset = len(positionals)
            elif offset < len(positionals):
                result[dest] = _convert(positionals[offset], spec)
                supplied.add(dest)
                offset += 1
            elif spec['required']:
                raise UsageError(f'missing required argument {dest}', code='missing_argument', parameter=dest)
            else:
                result[dest] = _default_value(spec, check=True)

        if offset < len(positionals):
            raise UsageError(f'unexpected argument {positionals[offset]!r}', code='unexpected_argument', value=positionals[offset])

        for rule in node.rules:
            parameters = rule['parameters']
            present = supplied.intersection(parameters)
            if rule['kind'] == 'exclusive' and len(present) > 1:
                raise UsageError('mutually exclusive parameters: ' + ', '.join(parameters), code='conflicting_parameters')

            if rule['kind'] == 'at_least_one' and not present:
                raise UsageError('supply at least one of: ' + ', '.join(parameters), code='missing_selection')

            if rule['kind'] == 'requires' and parameters[0] in present and len(present) != len(parameters):
                raise UsageError(parameters[0] + ' requires: ' + ', '.join(parameters[1:]), code='missing_dependency', parameter=parameters[0])

        return ParseResult(node, result, False)
    except UsageError as error:
        error.command = node.path
        raise
