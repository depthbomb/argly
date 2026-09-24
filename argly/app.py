from __future__ import annotations
import sys
from typing import Any, TextIO
from importlib import import_module
from argly.schema import validate_registry
from collections.abc import Callable, Iterable, Sequence
from argly._parser import Node, parse, UsageError, ParseResult

class Invocation:
    """A parsed invocation. Parsing does not import the selected handler."""

    __slots__ = ('path', 'values', 'kwargs', 'help_requested', '_node')

    def __init__(self, result: ParseResult) -> None:
        self.path = result.node.path
        self.values = result.values
        self.help_requested = result.help_requested
        self.kwargs = (
            {}
            if result.help_requested
            else {
                parameter: result.values[source]
                for parameter, source in result.node.bindings.items()
            }
        )
        self._node = result.node

class App:
    """A compiled command tree. Reuse it to avoid rebuilding parser tables."""

    __slots__ = ('name', 'registry', '_nodes', '_root', '_help_lookup', '_handlers')

    def __init__(
        self,
        name: str,
        commands: Iterable[Callable[..., Any]] = (),
        *,
        windows_options: bool = False,
        help_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        from argly.compiler import build_registry

        functions = tuple(commands)
        registry = build_registry(name, functions, windows_options=windows_options)
        self._initialize(registry, help_lookup)
        for function in functions:
            path = getattr(function, '__argly__')[0]  # noqa: B009
            handler = self._nodes[path].handler
            if handler is not None:
                self._handlers[path] = function

    def parse(self, args: Sequence[str]) -> Invocation:
        """Parse explicit arguments without calling handlers or writing output."""
        return Invocation(parse(self._root, list(args)))

    def run(
        self,
        args: Sequence[str] | None = None,
        *,
        out: TextIO | None = None,
        err: TextIO | None = None,
    ) -> int:
        """Return a handler's exit status, 0 for help, or 2 for usage errors."""
        output = sys.stdout if out is None else out
        errors = sys.stderr if err is None else err
        try:
            invocation = self.parse(sys.argv[1:] if args is None else args)
            # Invocation keeps the compiled node for dispatch within this module.
            # noinspection PyProtectedMember
            node = invocation._node
            if invocation.help_requested or node.handler is None:
                output.write(self.format_help(node.path))

                return 0

            handler = self._handlers.get(node.path)
            if handler is None:
                module_name, _, attribute = node.handler.partition(':')
                target: Any = import_module(module_name)
                for part in attribute.split('.'):
                    target = getattr(target, part)

                if not callable(target):
                    raise TypeError(f'handler {node.handler!r} is not callable')

                handler = target
                self._handlers[node.path] = handler

            code = handler(**invocation.kwargs)
            if type(code) is not int:
                raise TypeError(f'command {node.path or self.name!r} must return an int')

            return code
        except UsageError as error:
            errors.write(f'{self.name}: error: {error}\n')

            return 2

    def format_help(self, path: str = '') -> str:
        """Use generated help when available, otherwise render one page on demand."""
        if path not in self._nodes:
            raise ValueError(f'unknown command path {path!r}')

        if self._help_lookup is not None:
            text = self._help_lookup(path)
            if text is not None:
                return text

        from argly.helpgen import render

        return render(self.name, self._nodes[path])

    @classmethod
    def from_registry(
        cls,
        registry: dict[str, Any],
        *,
        help_lookup: Callable[[str], str | None] | None = None,
    ) -> App:
        """Load generated metadata without discovering or importing command modules."""
        app = cls.__new__(cls)
        app._initialize(registry, help_lookup)

        return app

    @classmethod
    def discover(cls, name: str, package: str, *, windows_options: bool = False) -> App:
        """Import a package's declarations for development or help generation."""
        from argly.compiler import discover

        return cls(name, discover(package), windows_options=windows_options)

    def _initialize(
        self,
        registry: dict[str, Any],
        help_lookup: Callable[[str], str | None] | None,
    ) -> None:
        self.registry = validate_registry(registry)
        self.name: str = self.registry['name']
        self._help_lookup = help_lookup
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._nodes: dict[str, Node] = {}
        for entry in self.registry['commands']:
            path = entry['path']
            parent = self._nodes.get(path.rpartition(' ')[0]) if path else None
            node = Node(entry, parent, self.registry['windows_options'])
            self._nodes[path] = node
            if parent is not None:
                parent.children[path.rpartition(' ')[2]] = node

        self._root = self._nodes['']
