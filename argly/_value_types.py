from typing import Any
from argly._references import resolve, validate_reference

def parse_extended(value: str, spec: dict[str, Any]) -> Any:
    kind = spec['type']
    if kind == 'uuid':
        from uuid import UUID

        return UUID(value)

    if kind in ('date', 'datetime'):
        from datetime import date, datetime

        return (date if kind == 'date' else datetime).fromisoformat(value)

    if kind == 'enum':
        member = spec['enum_members'].get(value)
        if member is None:
            raise ValueError('choose from ' + ', '.join(spec['choices']))

        return resolve(spec['enum'])[member]

    if kind == 'custom':
        return resolve(spec['converter'])(value)

    raise ValueError(f'unsupported value type: {kind}')

def validate_constraints(value: Any, spec: dict[str, Any]) -> None:
    if value is None:
        return

    rules = spec.get('constraints', {})
    minimum = rules.get('minimum')
    maximum = rules.get('maximum')
    if minimum is not None and not value >= minimum:
        raise ValueError(f'must be at least {minimum}')

    if maximum is not None and not value <= maximum:
        raise ValueError(f'must be at most {maximum}')

    path = rules.get('path')
    if path is None:
        return

    from os import R_OK, W_OK, access

    exists = path.get('exists')
    if exists is True and not value.exists():
        raise ValueError('path must exist')

    if exists is False and value.exists():
        raise ValueError('path must not exist')

    if path.get('kind') == 'file' and not value.is_file():
        raise ValueError('path must be a file')

    if path.get('kind') == 'directory' and not value.is_dir():
        raise ValueError('path must be a directory')

    if path.get('readable') and not access(value, R_OK):
        raise ValueError('path must be readable')

    if path.get('writable') and not access(value, W_OK):
        raise ValueError('path must be writable')

def validate_metadata(spec: dict[str, Any]) -> None:
    kind = spec['type']
    if kind == 'enum':
        validate_reference(spec.get('enum'))
        members = spec.get('enum_members')
        if not isinstance(members, dict) or not members or any(
            not isinstance(key, str) or not isinstance(value, str) or not value.isidentifier()
            for key, value in members.items()
        ):
            raise ValueError('enum_members must map CLI values to enum member names')

        choices = spec['choices']
        if not isinstance(choices, (list, tuple)) or not all(isinstance(choice, str) for choice in choices) or set(choices) != set(members) or len(choices) != len(members):
            raise ValueError('enum choices must match enum_members')

    if kind == 'custom':
        validate_reference(spec.get('converter'))

    rules = spec.get('constraints', {})
    if not isinstance(rules, dict) or set(rules) - {'minimum', 'maximum', 'path'}:
        raise ValueError('invalid value constraints')

    for name in ('minimum', 'maximum'):
        bound = rules.get(name)
        if bound is not None:
            from math import isfinite

            if kind not in ('int', 'float') or not isinstance(bound, (int, float)) or isinstance(bound, bool) or not isfinite(bound):
                raise ValueError('range bounds must be finite numbers on numeric parameters')

    if rules.get('minimum') is not None and rules.get('maximum') is not None and rules['minimum'] > rules['maximum']:
        raise ValueError('minimum cannot exceed maximum')

    if 'path' in rules:
        path = rules['path']
        if kind != 'path' or not isinstance(path, dict) or set(path) - {'exists', 'kind', 'readable', 'writable'}:
            raise ValueError('path constraints require a Path parameter')

        if path.get('exists') is not None and type(path['exists']) is not bool:
            raise ValueError('path exists must be a bool or None')

        if path.get('kind') not in (None, 'file', 'directory'):
            raise ValueError('path kind must be file or directory')

        if any(type(path.get(field, False)) is not bool for field in ('readable', 'writable')):
            raise ValueError('path access checks must be bools')

        if path.get('exists') is False and (path.get('kind') or path.get('readable') or path.get('writable')):
            raise ValueError('a nonexistent path cannot have kind or access constraints')
