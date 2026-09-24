from __future__ import annotations
from typing import Any, Optional


class UsageError(ValueError):
    """An invalid invocation, reported by App.run with exit status 2."""


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
    )

    def __init__(self, data: dict[str, Any], parent: Optional[Node], windows: bool) -> None:
        self.path: str = data['path']
        self.summary: str = data['summary']
        self.handler: Optional[str] = data['handler']
        self.bindings: dict[str, str] = data['bindings']
        self.arguments: list[dict[str, Any]] = [spec.copy() for spec in data['arguments']]
        self.children: dict[str, Node] = {}
        self.windows_options = windows
        self.options: list[dict[str, Any]] = ([] if parent is None else parent.options) + data[
            'options'
        ]
        self.lookup: dict[str, dict[str, Any]] = {}
        self.defaults: dict[str, Any] = {}
        self.required: list[str] = []
        for option in self.options:
            for spelling in option['names']:
                if windows or not spelling.startswith('/'):
                    self.lookup[spelling] = option

            self.defaults[option['dest']] = _default_value(option)
            if option['required']:
                self.required.append(option['dest'])

        for argument in self.arguments:
            argument['default'] = _default_value(argument)

        self.mutable_defaults = tuple(
            dest for dest, default in self.defaults.items() if isinstance(default, list)
        )


def _default_value(spec: dict[str, Any]) -> Any:
    default = spec['default']
    if default is not None and spec['type'] == 'path':
        if spec['multiple']:
            return [_convert(item, spec) for item in default]

        return _convert(default, spec)

    return default


def _convert(value: str, spec: dict[str, Any]) -> Any:
    kind = spec['type']
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
            raise ValueError(f'unsupported value type: {kind}')
    except (ValueError, OverflowError) as error:
        raise UsageError(f'{spec["dest"]}: invalid {kind} value {value!r}') from error

    choices = spec['choices']
    choice_value = value if kind == 'path' else result
    if choices is not None and choice_value not in choices:
        raise UsageError(f'{spec["dest"]}: choose from {", ".join(map(str, choices))}')

    return result


def _store(values: dict[str, Any], spec: dict[str, Any], value: Optional[str]) -> None:
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


def parse(root: Node, argv: list[str]) -> ParseResult:
    node = root
    values: dict[str, Any] = {}
    positionals: list[str] = []
    help_requested = False
    literal = False
    index = 0
    size = len(argv)
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
                    raise UsageError(f'{name} does not take a value')

                _store(values, spec, None)
                continue

            if not equal:
                if index == size or _looks_like_option(argv[index], node):
                    raise UsageError(
                        f"{name} requires a value (use {name}=VALUE for a value starting with '-')"
                    )

                attached = argv[index]
                index += 1

            _store(values, spec, attached)
            continue

        if token.startswith('--'):
            raise UsageError(f'unknown option {name!r}')

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
                    raise UsageError(f'unknown option {short!r}')

                offset += 1
                if spec['action'] != 'value':
                    _store(values, spec, None)
                    continue

                attached = token[offset:]
                if attached.startswith('='):
                    attached = attached[1:]
                elif not attached:
                    if index == size or _looks_like_option(argv[index], node):
                        raise UsageError(f'{short} requires a value')

                    attached = argv[index]
                    index += 1

                _store(values, spec, attached)
                break

            continue

        if node.children and not positionals:
            child = node.children.get(token)
            if child is None:
                raise UsageError(f'unknown command {token!r} under {node.path or "<root>"}')

            node = child
            continue

        positionals.append(token)

    if help_requested:
        return ParseResult(node, values, True)

    for dest in node.required:
        if dest not in values:
            raise UsageError(f'missing required option --{dest.replace("_", "-")}')

    result = node.defaults.copy()
    for dest in node.mutable_defaults:
        if dest not in values:
            result[dest] = result[dest].copy()

    result.update(values)
    offset = 0
    for spec in node.arguments:
        dest = spec['dest']
        if spec['multiple']:
            rest = positionals[offset:]
            if spec['required'] and not rest:
                raise UsageError(f'missing required argument {dest}')

            result[dest] = [_convert(value, spec) for value in rest] if rest else spec['default'][:]
            offset = len(positionals)
        elif offset < len(positionals):
            result[dest] = _convert(positionals[offset], spec)
            offset += 1
        elif spec['required']:
            raise UsageError(f'missing required argument {dest}')
        else:
            result[dest] = spec['default']

    if offset < len(positionals):
        raise UsageError(f'unexpected argument {positionals[offset]!r}')

    return ParseResult(node, result, False)
