from __future__ import annotations
from typing import Any
from types import ModuleType
from argly._parser import Node
from collections.abc import Mapping, Iterator

FORMAT_VERSION = 2

class _Children(Mapping[str, Node]):
    def __init__(self, paths: Mapping[str, str], nodes: _Nodes) -> None:
        self._paths = paths
        self._nodes = nodes

    def __getitem__(self, name: str) -> Node:
        return self._nodes[self._paths[name]]

    def __iter__(self) -> Iterator[str]:
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

class _Nodes(Mapping[str, Node]):
    def __init__(self, commands: Mapping[str, Any], windows: bool) -> None:
        self._commands = commands
        self._windows = windows
        self._cache: dict[str, Node] = {}

    def __getitem__(self, path: str) -> Node:
        cached = self._cache.get(path)
        if cached is not None:
            return cached

        data = self._commands[path]
        node = Node.__new__(Node)
        node.path = path
        node.summary = ''
        (
            node.handler, node.is_async, node.bindings, node.options,
            node.arguments, node.lookup, node.defaults, node.required,
            node.mutable_defaults, node.checked_defaults, node.rules,
            node.resources, children, node.bind, node.validate,
        ) = data
        node.windows_options = self._windows
        node.children = _Children(children, self)
        self._cache[path] = node

        return node

    def __iter__(self) -> Iterator[str]:
        return iter(self._commands)

    def __len__(self) -> int:
        return len(self._commands)

    def __contains__(self, path: object) -> bool:
        return path in self._commands

def load_nodes(plan: ModuleType) -> Mapping[str, Node]:
    """Check the execution format once, then materialize selected nodes only."""
    if getattr(plan, 'FORMAT_VERSION', None) != FORMAT_VERSION:
        raise ValueError('unsupported argly generated format; regenerate the application')

    commands = plan.COMMANDS
    if not isinstance(commands, Mapping) or '' not in commands:
        raise ValueError('generated plan is missing its root command; regenerate the application')

    return _Nodes(commands, plan.WINDOWS_OPTIONS)
