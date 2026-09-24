from __future__ import annotations
from typing import Any, TypeVar, Optional
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
        metavar: Optional[str] = None,
        choices: Optional[Iterable[str | int | float]] = None,
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
    def __init__(self, *, help: str = '', metavar: Optional[str] = None) -> None:
        self.help = help
        self.metavar = metavar


class Inherited:
    """Bind an ancestor option, using this parameter's name unless overridden."""

    __slots__ = ('name',)

    def __init__(self, name: Optional[str] = None) -> None:
        self.name = name


_F = TypeVar('_F', bound=Callable[..., Any])


def _decorate(path: str, summary: Optional[str], is_group: bool) -> Callable[[_F], _F]:
    parts = path.split()
    if path != ' '.join(parts) or any(part.startswith(('-', '/')) for part in parts):
        raise ValueError('command paths must contain names separated by single spaces')

    def decorate(function: _F) -> _F:
        if hasattr(function, '__argly__'):
            raise ValueError('a function can have only one command declaration')

        setattr(function, '__argly__', (path, summary, is_group))  # noqa: B010

        return function

    return decorate


def command(path: str, *, summary: Optional[str] = None) -> Callable[[_F], _F]:
    """Declare an integer-returning handler without inspecting or wrapping it."""
    return _decorate(path, summary, False)


def group(path: str, *, summary: Optional[str] = None) -> Callable[[_F], _F]:
    """Declare a namespace and inherited options. Its function is never called."""
    return _decorate(path, summary, True)
