from __future__ import annotations
from enum import Enum
from uuid import UUID
from pathlib import Path
from types import UnionType
from pkgutil import walk_packages
from datetime import date, datetime
from importlib import import_module
from collections.abc import Callable, Iterable
from argly._references import resolve, validate_reference
from argly.schema import empty_command, validate_registry
from inspect import cleandoc, Parameter, signature, iscoroutinefunction
from typing import Any, Union, Literal, get_args, Annotated, get_origin, get_type_hints
from argly.declarations import Flag, Count, Range, Option, Argument, PathRule, Resource, Converter, Inherited

def _shape(annotation: Any, converter: Converter | None = None) -> tuple[str, bool, bool, list[Any] | None, dict[str, Any]]:
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

    details: dict[str, Any] = {}
    kind: str | None
    supported: dict[Any, str] = {str: 'str', int: 'int', float: 'float', bool: 'bool', Path: 'path', UUID: 'uuid', date: 'date', datetime: 'datetime'}
    if converter is not None:
        if choices is not None:
            raise ValueError('Converter cannot be combined with Literal')

        validate_reference(converter.parser)
        if converter.serializer is not None:
            validate_reference(converter.serializer)

        kind = 'custom'
        details['converter'] = converter.parser
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        members = list(annotation)
        if not members or len({type(member.value) for member in members}) != 1 or type(members[0].value) not in (str, int):
            raise ValueError('enum values must be nonempty and uniformly str or int')

        kind = 'enum'
        details['enum'] = f'{annotation.__module__}:{annotation.__qualname__}'
        validate_reference(details['enum'])
        details['enum_members'] = {str(member.value): member.name for member in members}
        choices = list(details['enum_members'])
    else:
        kind = supported.get(annotation)
    if kind is None:
        display = f'{annotation.__module__}.{annotation.__qualname__}' if isinstance(annotation, type) else repr(annotation)
        raise ValueError(
            f'unsupported CLI annotation {display}; use a supported scalar, Enum, Literal, list, or Converter'
        )

    if nullable and multiple:
        raise ValueError('use list[T] with an empty default instead of Optional[list[T]]')

    return kind, multiple, nullable, choices, details

def _default(value: Any, kind: str, multiple: bool, nullable: bool, details: dict[str, Any], converter: Converter | None = None) -> Any:
    if value is None and nullable:
        return None

    if multiple:
        if not isinstance(value, (list, tuple)):
            raise ValueError('list options and arguments need a list or tuple default')

        return [_default(item, kind, False, False, details, converter) for item in value]

    if kind == 'custom':
        if converter is None or converter.serializer is None:
            raise ValueError('custom defaults and choices need a Converter serializer')

        text = resolve(converter.serializer)(value)
        if not isinstance(text, str):
            raise ValueError('a Converter serializer must return str')

        return text

    if kind == 'enum':
        if not isinstance(value, Enum) or f'{type(value).__module__}:{type(value).__qualname__}' != details['enum']:
            raise ValueError('default must be a member of the declared enum')

        return str(value.value)

    if kind in ('uuid', 'date', 'datetime'):
        expected_type = {'uuid': UUID, 'date': date, 'datetime': datetime}[kind]
        if type(value) is not expected_type:
            raise ValueError(f'default {value!r} does not match {kind}')

        return value.isoformat() if isinstance(value, date) else str(value)

    if kind == 'path' and isinstance(value, (str, Path)):
        return Path(value).as_posix()

    expected = {'str': str, 'int': int, 'float': float, 'bool': bool, 'path': str}[kind]
    if type(value) is not expected:
        raise ValueError(f'default {value!r} does not match {kind}')

    if kind == 'float' and (value != value or value in (float('inf'), float('-inf'))):
        raise ValueError('non-finite defaults cannot be generated')

    return value

def _definition(function: Callable[..., Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    declaration = getattr(function, '__argly__', None)
    if not isinstance(declaration, tuple) or len(declaration) != 3:
        raise ValueError(f'{function.__name__} needs @command or @group')

    path, summary, is_group = declaration
    hints = get_type_hints(function, include_extras=True)
    if not is_group and hints.get('return') is not int:
        raise ValueError(f'{path!r}: command handlers must declare -> int')

    entry = empty_command(path)
    if iscoroutinefunction(function) and not is_group:
        entry['async'] = True
    rules = getattr(function, '__argly_rules__', ())
    if rules:
        entry['rules'] = [{'kind': rule.kind, 'parameters': list(rule.parameters)} for rule in rules]
    entry['summary'] = summary if summary is not None else cleandoc(function.__doc__ or '')
    if not is_group:
        module_name = getattr(function, '__module__')  # noqa: B009
        entry['handler'] = f'{module_name}:{function.__qualname__}'

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
        markers = [item for item in metadata if isinstance(item, (Option, Argument, Inherited, Resource))]
        if len(markers) != 1:
            raise ValueError(f'{path!r}: {parameter.name} needs exactly one CLI marker')

        marker = markers[0]
        if isinstance(marker, Resource):
            if is_group or parameter.default is not Parameter.empty:
                raise ValueError('Resource parameters belong to commands and cannot have defaults')

            if any(isinstance(item, (Range, PathRule, Converter)) for item in metadata):
                raise ValueError('Resource parameters cannot have CLI value constraints')

            entry.setdefault('resources', {})[parameter.name] = marker.name or parameter.name
            continue

        converters = [item for item in metadata if isinstance(item, Converter)]
        if len(converters) > 1:
            raise ValueError(f'{parameter.name}: only one Converter is allowed')

        converter = converters[0] if converters else None
        kind, multiple, nullable, choices, details = _shape(underlying, converter)
        if isinstance(marker, Inherited):
            if any(isinstance(item, (Range, PathRule)) for item in metadata):
                raise ValueError('declare inherited constraints on the ancestor parameter')

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
                    **details,
                }
            )
            continue

        required = parameter.default is Parameter.empty
        default = None if required else _default(parameter.default, kind, multiple, nullable, details, converter)
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

            choices = [_default(item, kind, False, False, details, converter) for item in marker.choices]

        if isinstance(marker, (Flag, Count)) and choices is not None:
            raise ValueError(
                f'{parameter.name}: choices apply to value options, not flags or counters'
            )

        if choices is not None and not required and default is not None:
            defaults = default if isinstance(default, list) else [default]
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
            **details,
        }
        constraints: dict[str, Any] = {}
        for item in metadata:
            if isinstance(item, Range):
                if 'minimum' in constraints:
                    raise ValueError(f'{parameter.name}: only one Range is allowed')

                constraints.update(minimum=item.minimum, maximum=item.maximum)
            elif isinstance(item, PathRule):
                if 'path' in constraints:
                    raise ValueError(f'{parameter.name}: only one PathRule is allowed')

                constraints['path'] = {field: getattr(item, field) for field in ('exists', 'kind', 'readable', 'writable')}

        if constraints:
            spec['constraints'] = constraints

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

            for field in ('enum', 'converter'):
                if source.get(field) != request.get(field):
                    raise ValueError(f'{path!r}: inherited parameter has a different {field}')

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
