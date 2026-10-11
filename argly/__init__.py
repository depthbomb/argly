from __future__ import annotations

# Python 3.15 loads exports on demand; 3.14 keeps ordinary imports.
__lazy_modules__ = ('argly.app', 'argly._parser', 'argly.declarations')

from argly._parser import UsageError
from argly.app import App, Invocation
from argly.declarations import Flag, Count, Range, group, Option, command, Argument, PathRule, Requires, Resource, Converter, Inherited, AtLeastOne, MutuallyExclusive

__all__ = [
    'App',
    'Argument',
    'Count',
    'Flag',
    'Inherited',
    'Invocation',
    'Option',
    'UsageError',
    'command',
    'group',
    'Range',
    'PathRule',
    'Requires',
    'AtLeastOne',
    'Converter',
    'MutuallyExclusive',
    'Resource',
]
