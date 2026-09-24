from __future__ import annotations
from typing import Any, TypeVar
from collections.abc import Callable, Iterable

class Option:
    """A value option. The parameter supplies its long name, type, and default."""

    __slots__ = ('names', 'help', 'metavar', 'choices')

    # The public help= keyword describes the command-line parameter.
    # noinspection PyShadowingBuiltins
    def __init__(
        self,
        *names: str,
        help: str = '',
        metavar: str | None = None,
        choices: Iterable[str | int | float] | None = None,
    ) -> None:
        self.names = names
        self.help = help
        self.metavar = metavar
        self.choices = None if choices is None else tuple(choices)

class Flag(Option):
    """A boolean switch; supplying it inverts the declared default."""

    __slots__ = ()

class Count(Option):
    """An integer counter incremented for each occurrence."""

    __slots__ = ()

class Argument:
    """A positional value; list[T] consumes all remaining positional values."""

    __slots__ = ('help', 'metavar')

    # Keep the same help= keyword as Option.
    # noinspection PyShadowingBuiltins
    def __init__(self, *, help: str = '', metavar: str | None = None) -> None:
        self.help = help
        self.metavar = metavar

class Inherited:
    """Bind an ancestor option, using this parameter's name unless overridden."""

    __slots__ = ('name',)

    def __init__(self, name: str | None = None) -> None:
        self.name = name

_F = TypeVar('_F', bound=Callable[..., Any])

class Range:
    """Inclusive numeric limits used alongside a CLI marker in Annotated."""

    __slots__ = ('minimum', 'maximum')

    def __init__(self, minimum: int | float | None = None, maximum: int | float | None = None) -> None:
        self.minimum = minimum
        self.maximum = maximum

class PathRule:
    """Path checks performed when parsing, including defaults, but never for help.

    kind may be 'file' or 'directory' and implies existence. exists=False requires
    a new path. readable and writable check access to an existing path.
    """

    __slots__ = ('exists', 'kind', 'readable', 'writable')

    def __init__(self, *, exists: bool | None = None, kind: str | None = None, readable: bool = False, writable: bool = False) -> None:
        self.exists = exists
        self.kind = kind
        self.readable = readable
        self.writable = writable

class Converter:
    """An importable string parser for a custom Annotated type.

    parser and serializer are module:attribute references. A serializer is needed
    for concrete defaults and choices; it must return text the parser can read.
    Runtime loading of the registry never imports either callback.
    """

    __slots__ = ('parser', 'serializer')

    def __init__(self, parser: str, *, serializer: str | None = None) -> None:
        self.parser = parser
        self.serializer = serializer

class Relation:
    """A rule over explicitly supplied parameter names, including inherited options."""

    __slots__ = ('kind', 'parameters')

    def __init__(self, kind: str, parameters: Iterable[str]) -> None:
        self.kind = kind
        self.parameters = tuple(parameters)

class MutuallyExclusive(Relation):
    __slots__ = ()

    def __init__(self, *parameters: str) -> None:
        super().__init__('exclusive', parameters)

class AtLeastOne(Relation):
    __slots__ = ()

    def __init__(self, *parameters: str) -> None:
        super().__init__('at_least_one', parameters)

class Requires(Relation):
    __slots__ = ()

    def __init__(self, parameter: str, *dependencies: str) -> None:
        super().__init__('requires', (parameter, *dependencies))

def _decorate(path: str, summary: str | None, is_group: bool, rules: Iterable[Relation]) -> Callable[[_F], _F]:
    parts = path.split()
    if path != ' '.join(parts) or any(part.startswith(('-', '/')) for part in parts):
        raise ValueError('command paths must contain names separated by single spaces')

    constraints = tuple(rules)

    def decorate(function: _F) -> _F:
        if hasattr(function, '__argly__'):
            raise ValueError('a function can have only one command declaration')

        setattr(function, '__argly__', (path, summary, is_group))  # noqa: B010
        if constraints:
            setattr(function, '__argly_rules__', constraints)  # noqa: B010

        return function

    return decorate

def command(path: str, *, summary: str | None = None, rules: Iterable[Relation] = ()) -> Callable[[_F], _F]:
    """Declare an integer-returning handler without inspecting or wrapping it."""
    return _decorate(path, summary, False, rules)

def group(path: str, *, summary: str | None = None, rules: Iterable[Relation] = ()) -> Callable[[_F], _F]:
    """Declare a namespace and inherited options. Its function is never called."""
    return _decorate(path, summary, True, rules)
