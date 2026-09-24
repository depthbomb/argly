from typing import Any
from importlib import import_module

def validate_reference(reference: object) -> None:
    """Check an import reference without importing its module."""
    if not isinstance(reference, str):
        raise ValueError('an import reference must be a module:attribute string')

    module, separator, attribute = reference.partition(':')
    if not separator or not all(part.isidentifier() for part in (*module.split('.'), *attribute.split('.'))):
        raise ValueError(f'invalid import reference {reference!r}; expected module:attribute')

def resolve(reference: str) -> Any:
    validate_reference(reference)
    module, _, attribute = reference.partition(':')
    target: Any = import_module(module)
    for part in attribute.split('.'):
        target = getattr(target, part)

    return target
