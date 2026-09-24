from __future__ import annotations
import sys
from typing import Any, TextIO
from argly.schema import validate_registry
from argly._references import resolve, validate_reference
from argly._parser import Node, parse, UsageError, ParseResult
from collections.abc import Mapping, Callable, Iterable, Sequence

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

    __slots__ = ('name', 'registry', '_nodes', '_root', '_help_lookup', '_handlers', '_resources')

    def __init__(
        self,
        name: str,
        commands: Iterable[Callable[..., Any]] = (),
        *,
        windows_options: bool = False,
        help_lookup: Callable[[str], str | None] | None = None,
        resources: Mapping[str, str | Callable[[Invocation], Any]] | None = None,
    ) -> None:
        from argly.compiler import build_registry

        functions = tuple(commands)
        registry = build_registry(name, functions, windows_options=windows_options)
        self._initialize(registry, help_lookup, resources)
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
        """Run a command, starting an event loop for async handlers or resources.

        In an existing event loop, await run_async() for those commands instead.
        Return the handler's integer status, 0 for help, or 2 for usage errors.
        """
        output = sys.stdout if out is None else out
        errors = sys.stderr if err is None else err
        path = ''
        try:
            invocation = self._prepare(args, output)
            if isinstance(invocation, int):
                return invocation

            path = invocation.path
            node = self._nodes[path]
            if node.is_async or node.resources:
                from asyncio import run, get_running_loop

                try:
                    get_running_loop()
                except RuntimeError:
                    running = False
                else:
                    running = True

                if running:
                    raise RuntimeError('an event loop is already running; await App.run_async() instead')

                return run(self._invoke_async(invocation))

            return self._exit_code(self._handler(node)(**invocation.kwargs), path)
        except UsageError as error:
            if not error.command:
                error.command = path

            errors.write(self.format_error(error))

            return 2

    async def run_async(self, args: Sequence[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None) -> int:
        """Run sync or async handlers in the caller's event loop.

        Resources are entered once per invocation and unwound in reverse order.
        Handler exceptions and cancellation propagate after cleanup. A resource
        that intentionally suppresses an exception makes the invocation return 0.
        """
        output = sys.stdout if out is None else out
        errors = sys.stderr if err is None else err
        path = ''
        try:
            invocation = self._prepare(args, output)
            if isinstance(invocation, int):
                return invocation

            path = invocation.path
            return await self._invoke_async(invocation)
        except UsageError as error:
            if not error.command:
                error.command = path

            errors.write(self.format_error(error))

            return 2

    def format_error(self, error: UsageError) -> str:
        """Render a usage failure. Override this method to customize presentation."""
        path = error.command if error.command in self._nodes else ''
        help_lines = self.format_help(path).splitlines()
        usage = help_lines[0] if help_lines else f'Usage: {self.name}' + (' ' + path if path else '')
        lines = [usage, f'{self.name}: error: {error}']
        if error.suggestions:
            lines.append('Did you mean: ' + ', '.join(error.suggestions) + '?')

        return '\n'.join(lines) + '\n'

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
        resources: Mapping[str, str | Callable[[Invocation], Any]] | None = None,
    ) -> App:
        """Load generated metadata without discovering or importing command modules."""
        app = cls.__new__(cls)
        app._initialize(registry, help_lookup, resources)

        return app

    @classmethod
    def discover(cls, name: str, package: str, *, windows_options: bool = False, resources: Mapping[str, str | Callable[[Invocation], Any]] | None = None) -> App:
        """Import a package's declarations for development or help generation."""
        from argly.compiler import discover

        return cls(name, discover(package), windows_options=windows_options, resources=resources)

    def _prepare(self, args: Sequence[str] | None, output: TextIO) -> Invocation | int:
        arguments = list(sys.argv[1:] if args is None else args)
        invocation = self.parse(arguments)
        node = self._nodes[invocation.path]
        if invocation.help_requested or node.handler is None:
            output.write(self.format_help(node.path))

            return 0

        return invocation

    def _handler(self, node: Node) -> Callable[..., Any]:
        handler = self._handlers.get(node.path)
        if handler is None:
            assert node.handler is not None
            target = resolve(node.handler)
            if not callable(target):
                raise TypeError(f'handler {node.handler!r} is not callable')

            handler = target
            self._handlers[node.path] = handler

        return handler

    def _exit_code(self, code: Any, path: str) -> int:
        if type(code) is not int:
            from inspect import iscoroutine

            if iscoroutine(code):
                code.close()

            raise TypeError(f'command {path or self.name!r} must return an int')

        return code

    async def _invoke_async(self, invocation: Invocation) -> int:
        from inspect import isawaitable
        from contextlib import AsyncExitStack

        node = self._nodes[invocation.path]
        handler = self._handler(node)
        kwargs = invocation.kwargs.copy()
        shared: dict[str, Any] = {}
        code = 0
        async with AsyncExitStack() as stack:
            for parameter, name in node.resources.items():
                if name not in shared:
                    provider = self._resources.get(name)
                    if provider is None:
                        raise ValueError(f'no resource provider registered for {name!r}')

                    factory = resolve(provider) if isinstance(provider, str) else provider
                    manager = factory(invocation)
                    if isawaitable(manager):
                        manager = await manager

                    if hasattr(manager, '__aenter__'):
                        shared[name] = await stack.enter_async_context(manager)
                    else:
                        shared[name] = stack.enter_context(manager)

                kwargs[parameter] = shared[name]

            result = handler(**kwargs)
            if isawaitable(result):
                result = await result

            code = self._exit_code(result, node.path)

        return code

    def _initialize(
        self,
        registry: dict[str, Any],
        help_lookup: Callable[[str], str | None] | None,
        resources: Mapping[str, str | Callable[[Invocation], Any]] | None,
    ) -> None:
        self.registry = validate_registry(registry)
        self.name: str = self.registry['name']
        self._help_lookup = help_lookup
        self._resources = dict(resources or {})
        for name, provider in self._resources.items():
            if not isinstance(name, str) or not name.isidentifier():
                raise ValueError('resource names must be identifiers')

            if isinstance(provider, str):
                validate_reference(provider)
            elif not callable(provider):
                raise ValueError(f'resource provider {name!r} must be callable or an import reference')
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
