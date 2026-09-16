from __future__ import annotations
from pathlib import Path
from types import UnionType
from pkgutil import walk_packages
from importlib import import_module
from collections.abc import Callable, Iterable
from argly.schema import empty_command, validate_registry
from argly.declarations import Option, Flag, Count, Argument, Inherited
from inspect import Parameter, signature, cleandoc, iscoroutinefunction
from typing import Any, Union, Literal, Optional, Annotated, get_args, get_origin, get_type_hints


def _shape(annotation: Any) -> tuple[str, bool, bool, Optional[list[Any]]]:
    nullable = False
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        args = get_args(annotation)
        if len(args) != 2 or type(None) not in args:
            raise ValueError('only Optional[T] unions are supported')

        nullable = True
        annotation = next(item for item in args if item is not type(None))

    multiple = get_origin(annotation) is list
    if multiple:
        annotation = get_args(annotation)[0]

    choices = None
    if get_origin(annotation) is Literal:
        choices = list(get_args(annotation))
        types = {type(item) for item in choices}
        if len(types) != 1:
            raise ValueError('Literal choices must all have the same type')

        annotation = type(choices[0])

    supported = {str: 'str', int: 'int', float: 'float', bool: 'bool', Path: 'path'}
    kind = supported.get(annotation)
    if kind is None:
        raise ValueError(
            f'unsupported CLI annotation {annotation!r}; use str, int, float, bool, Path, Literal, Optional, or list'
        )

    if nullable and multiple:
        raise ValueError('use list[T] with an empty default instead of Optional[list[T]]')

    return kind, multiple, nullable, choices


def _default(value: Any, kind: str, multiple: bool, nullable: bool) -> Any:
    if value is None and nullable:
        return None

    if multiple:
        if not isinstance(value, (list, tuple)):
            raise ValueError('list options and arguments need a list or tuple default')

        return [_default(item, kind, False, False) for item in value]

    if kind == 'path' and isinstance(value, (str, Path)):
        return str(Path(value))

    expected = {'str': str, 'int': int, 'float': float, 'bool': bool, 'path': str}[kind]
    if type(value) is not expected:
        raise ValueError(f'default {value!r} does not match {kind}')

    if kind == 'float' and (value != value or value in (float('inf'), float('-inf'))):
        raise ValueError('non-finite defaults cannot be generated')

    return value


def _definition(function: Callable[..., Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    declaration = getattr(function, '__argly__', None)
    if declaration is None:
        raise ValueError(f'{function.__name__} needs @command or @group')

    if iscoroutinefunction(function):
        raise ValueError('command handlers must be synchronous')

    path, summary, is_group = declaration
    hints = get_type_hints(function, include_extras=True)
    if not is_group and hints.get('return') is not int:
        raise ValueError(f'{path!r}: command handlers must declare -> int')

    entry = empty_command(path)
    entry['summary'] = summary if summary is not None else cleandoc(function.__doc__ or '')
    entry['handler'] = None if is_group else f'{function.__module__}:{function.__qualname__}'
    inherited = []
    for parameter in signature(function).parameters.values():
        if parameter.kind in (
            Parameter.POSITIONAL_ONLY,
            Parameter.VAR_POSITIONAL,
            Parameter.VAR_KEYWORD,
        ):
            raise ValueError(
                f'{path!r}: positional-only parameters, *args, and **kwargs are unsupported'
            )

        annotation = hints.get(parameter.name)
        if get_origin(annotation) is not Annotated:
            raise ValueError(f'{path!r}: {parameter.name} needs Annotated[T, CLI metadata]')

        underlying, *metadata = get_args(annotation)
        markers = [item for item in metadata if isinstance(item, (Option, Argument, Inherited))]
        if len(markers) != 1:
            raise ValueError(f'{path!r}: {parameter.name} needs exactly one CLI marker')

        marker = markers[0]
        kind, multiple, nullable, choices = _shape(underlying)
        if isinstance(marker, Inherited):
            if parameter.default is not Parameter.empty:
                raise ValueError(
                    f'{parameter.name}: Inherited() takes its default from the ancestor'
                )

            source = marker.name or parameter.name
            entry['bindings'][parameter.name] = source
            inherited.append(
                {
                    'parameter': parameter.name,
                    'source': source,
                    'type': kind,
                    'multiple': multiple,
                    'nullable': nullable,
                    'choices': choices,
                }
            )
            continue

        required = parameter.default is Parameter.empty
        default = None if required else _default(parameter.default, kind, multiple, nullable)
        if multiple and required:
            default = []

        if isinstance(marker, (Flag, Count)):
            expected = 'bool' if isinstance(marker, Flag) else 'int'
            if kind != expected or multiple or nullable:
                raise ValueError(f'{parameter.name}: {type(marker).__name__} requires {expected}')

            if required:
                default = False if isinstance(marker, Flag) else 0
                required = False

        if isinstance(marker, Option) and marker.choices is not None:
            if choices is not None and list(marker.choices) != choices:
                raise ValueError(f'{parameter.name}: Option choices disagree with Literal')

            choices = [_default(item, kind, False, False) for item in marker.choices]

        if isinstance(marker, (Flag, Count)) and choices is not None:
            raise ValueError(
                f'{parameter.name}: choices apply to value options, not flags or counters'
            )

        if choices is not None and not required and default is not None:
            defaults = default if multiple else [default]
            if any(item not in choices for item in defaults):
                raise ValueError(f'{parameter.name}: default is outside the choices')

        spec = {
            'dest': parameter.name,
            'type': kind,
            'multiple': multiple,
            'nullable': nullable,
            'choices': choices,
            'default': default,
            'required': required,
            'help': marker.help,
            'metavar': marker.metavar or parameter.name.upper(),
        }
        if isinstance(marker, Option):
            canonical = '--' + parameter.name.replace('_', '-')
            spec['names'] = list(dict.fromkeys((canonical, *marker.names)))
            spec['action'] = (
                'flag'
                if isinstance(marker, Flag)
                else 'count'
                if isinstance(marker, Count)
                else 'value'
            )
            if kind == 'bool' and spec['action'] == 'value':
                raise ValueError(f'{parameter.name}: use Flag() for bool options')

            entry['options'].append(spec)
        else:
            if is_group:
                raise ValueError('groups can declare options, but not positional arguments')

            entry['arguments'].append(spec)

        entry['bindings'][parameter.name] = parameter.name

    return entry, inherited


def build_registry(
    name: str,
    commands: Iterable[Callable[..., Any]],
    *,
    windows_options: bool = False,
) -> dict[str, Any]:
    """Resolve signatures and inheritance once, producing portable parser metadata."""
    entries: dict[str, dict[str, Any]] = {}
    requests: dict[str, list[dict[str, Any]]] = {}
    for function in commands:
        entry, inherited = _definition(function)
        path = entry['path']
        if path in entries:
            raise ValueError(f'duplicate command {path!r}')

        entries[path] = entry
        requests[path] = inherited

    for path in tuple(entries):
        parts = path.split()
        for length in range(len(parts)):
            parent = ' '.join(parts[:length])
            entries.setdefault(parent, empty_command(parent))

    entries.setdefault('', empty_command(''))
    for path, inherited in requests.items():
        ancestors: dict[str, dict[str, Any]] = {}
        parts = path.split()
        for length in range(len(parts)):
            parent_entry = entries[' '.join(parts[:length])]
            ancestors.update({option['dest']: option for option in parent_entry['options']})

        for request in inherited:
            source = ancestors.get(request['source'])
            if source is None:
                raise ValueError(f'{path!r}: no ancestor option {request["source"]!r}')

            for field in ('type', 'multiple', 'nullable'):
                if source[field] != request[field]:
                    raise ValueError(
                        f'{path!r}: inherited parameter {request["parameter"]!r} has a different type'
                    )

            if request['choices'] is not None and request['choices'] != source['choices']:
                raise ValueError(f'{path!r}: inherited Literal choices disagree with ancestor')

    registry = {
        'version': 1,
        'name': name,
        'windows_options': windows_options,
        'commands': list(entries.values()),
    }

    return validate_registry(registry)


def discover(package: str) -> list[Callable[..., Any]]:
    """Find decorated module-level functions in a package, in stable module order."""
    root = import_module(package)
    modules = [root]
    package_paths = getattr(root, '__path__', None)
    if package_paths is not None:
        names = sorted(info.name for info in walk_packages(package_paths, root.__name__ + '.'))
        modules.extend(import_module(name) for name in names)

    found = []
    seen = set()
    for module in modules:
        for _, value in sorted(vars(module).items()):
            if (
                callable(value)
                and getattr(value, '__module__', None) == module.__name__
                and hasattr(value, '__argly__')
                and id(value) not in seen
            ):
                found.append(value)
                seen.add(id(value))

    return found
