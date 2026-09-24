import sys
import pytest
from enum import Enum
from uuid import UUID
from pathlib import Path
from typing import Annotated
from argly.helpgen import source
from datetime import date, datetime
from argly import App, Flag, Count, Range, group, Option, command, Argument, PathRule, Requires, Converter, Inherited, AtLeastOne, UsageError, MutuallyExclusive

class Color(Enum):
    RED = 'red'
    BLUE = 'blue'

class Level(Enum):
    LOW = 1
    HIGH = 2

ZERO_UUID = UUID(int=0)

@command('types')
def extended(
    *,
    color: Annotated[Color, Option()] = Color.RED,
    level: Annotated[Level, Option()] = Level.HIGH,
    identifier: Annotated[UUID, Option()] = ZERO_UUID,
    day: Annotated[date, Option()] = date(2025, 1, 2),
    moment: Annotated[datetime, Option()] = datetime(2025, 1, 2, 3, 4),
    colors: Annotated[list[Color], Option()] = (),
) -> int:
    return 0

def test_extended_types_defaults_and_generation():
    namespace = {}
    exec(source(App('tool', [extended])), namespace)
    app = App.from_registry(namespace['REGISTRY'])
    defaults = app.parse(['types']).kwargs
    assert defaults == dict(color=Color.RED, level=Level.HIGH, identifier=UUID(int=0), day=date(2025, 1, 2), moment=datetime(2025, 1, 2, 3, 4), colors=[])
    result = app.parse(['types', '--color=blue', '--level=1', '--identifier=12345678-1234-1234-1234-123456789abc', '--day=2026-09-24', '--moment=2026-09-24T12:30:00+00:00', '--colors=red', '--colors=blue']).kwargs
    assert result['color'] is Color.BLUE
    assert result['level'] is Level.LOW
    assert result['identifier'] == UUID('12345678-1234-1234-1234-123456789abc')
    assert result['day'] == date(2026, 9, 24)
    assert result['moment'].utcoffset().total_seconds() == 0
    assert result['colors'] == [Color.RED, Color.BLUE]

@pytest.mark.parametrize('option', ['--color=nope', '--identifier=nope', '--day=2026-02-30', '--moment=nope'])
def test_extended_invalid_values(option):
    with pytest.raises(UsageError):
        App('tool', [extended]).parse(['types', option])

def test_ranges_and_count_validation():
    @command('')
    def bounded(*, number: Annotated[int, Option(), Range(1, 5)] = 2, count: Annotated[int, Count('-c'), Range(0, 2)] = 0) -> int:
        return 0

    app = App('tool', [bounded])
    assert app.parse(['--number=5', '-cc']).kwargs == {'number': 5, 'count': 2}
    with pytest.raises(UsageError, match='at least 1'):
        app.parse(['--number=0'])
    with pytest.raises(UsageError, match='at most 2'):
        app.parse(['-ccc'])

def test_path_checks_happen_at_parse_time(tmp_path):
    missing = tmp_path / 'missing'

    @command('')
    def read(path: Annotated[Path, Argument(), PathRule(kind='file', readable=True)] = missing) -> int:
        return 0

    app = App.from_registry(App('tool', [read]).registry)
    assert 'Usage:' in app.format_help()
    assert app.parse(['--help']).help_requested
    with pytest.raises(UsageError, match='must be a file'):
        app.parse([])
    missing.write_text('hello')
    assert app.parse([]).kwargs['path'] == missing
    with pytest.raises(UsageError, match='must be a file'):
        app.parse([str(tmp_path)])

def test_custom_codec_is_lazy_and_defaults_are_detached(tmp_path, monkeypatch):
    module = tmp_path / 'argly_test_codec.py'
    module.write_text('def decode(text):\n    return {"value": text}\ndef encode(value):\n    return value["value"]\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    default = {'value': 'default'}

    @command('')
    def custom(*, item: Annotated[dict, Option(), Converter('argly_test_codec:decode', serializer='argly_test_codec:encode')] = default) -> int:
        return 0

    try:
        registry = App('tool', [custom]).registry
        sys.modules.pop('argly_test_codec', None)
        app = App.from_registry(registry)
        app.format_help()
        assert 'argly_test_codec' not in sys.modules
        first = app.parse([]).kwargs['item']
        assert first == {'value': 'default'}
        first['value'] = 'changed'
        assert app.parse([]).kwargs['item'] == {'value': 'default'}
        assert app.parse(['--item=explicit']).kwargs['item'] == {'value': 'explicit'}
    finally:
        sys.modules.pop('argly_test_codec', None)

def test_custom_default_requires_serializer():
    @command('')
    def custom(*, value: Annotated[str, Option(), Converter('builtins:str')] = 'default') -> int:
        return 0

    with pytest.raises(ValueError, match='serializer'):
        App('tool', [custom])

def test_parameter_relationships_use_explicit_presence():
    @command('', rules=[MutuallyExclusive('json', 'text'), Requires('user', 'password'), AtLeastOne('json', 'text')])
    def relationships(
        *,
        json: Annotated[bool, Flag()] = False,
        text: Annotated[bool, Flag()] = False,
        user: Annotated[str, Option()] = '',
        password: Annotated[str, Option()] = '',
    ) -> int:
        return 0

    app = App.from_registry(App('tool', [relationships]).registry)
    assert app.parse(['--text']).kwargs['text'] is True
    assert app.parse(['--help']).help_requested
    with pytest.raises(UsageError, match='at least one'):
        app.parse([])
    with pytest.raises(UsageError, match='mutually exclusive'):
        app.parse(['--json', '--text'])
    with pytest.raises(UsageError, match='user requires: password'):
        app.parse(['--text', '--user=me'])
    assert app.parse(['--text', '--user=me', '--password=']).kwargs['user'] == 'me'

def test_group_relationships_are_inherited():
    @group('', rules=[MutuallyExclusive('quiet', 'verbose')])
    def root(*, quiet: Annotated[bool, Flag()] = False, verbose: Annotated[bool, Flag()] = False) -> None:
        pass

    @command('child')
    def child(quiet: Annotated[bool, Inherited()]) -> int:
        return 0

    app = App('tool', [root, child])
    with pytest.raises(UsageError, match='mutually exclusive'):
        app.parse(['--quiet', 'child', '--verbose'])

@pytest.mark.parametrize('constraint', [Range(5, 1), Range(float('nan')), PathRule(kind='bad')])
def test_invalid_constraint_metadata(constraint):
    @command('')
    def bad(value) -> int:
        return 0

    bad.__annotations__['value'] = Annotated[int, Argument(), constraint]
    with pytest.raises(ValueError):
        App('tool', [bad])

def test_invalid_rule_parameter():
    @command('', rules=[AtLeastOne('missing')])
    def bad() -> int:
        return 0

    with pytest.raises(ValueError, match='declared names'):
        App('tool', [bad])
