import pytest
from pathlib import Path
from typing import Literal, Optional, Annotated
from argly import App, Flag, Count, Option, Argument, UsageError, command

@pytest.fixture
def registry():
    @command('')
    def values(
        files: Annotated[list[Path], Argument()] = (),
        *,
        required: Annotated[int, Option()],
        many: Annotated[list[int], Option()],
        number: Annotated[int, Count()] = 0,
        force: Annotated[bool, Flag()] = False,
        ratio: Annotated[float, Option()] = 1.0,
        text: Annotated[str, Option()] = 'hello',
        tags: Annotated[list[int], Option()] = (),
        mode: Annotated[Literal['fast', 'slow'], Option()] = 'fast',
        modes: Annotated[list[Literal['fast', 'slow']], Option()] = ('fast',),
        path: Annotated[Path, Option(choices=['data/input'])] = Path('data/input'),
        optional: Annotated[Optional[int], Option()] = None,
    ) -> int:
        return 0

    return App('tool', [values]).registry

@pytest.mark.parametrize(
    'dest, changes',
    [
        ('number', {'default': 'broken'}),
        ('number', {'default': True}),
        ('number', {'default': None}),
        ('force', {'default': 1}),
        ('ratio', {'default': 1}),
        ('ratio', {'default': float('inf')}),
        ('ratio', {'default': float('nan')}),
        ('text', {'default': ['hello']}),
        ('tags', {'default': None}),
        ('tags', {'default': 1}),
        ('tags', {'default': ['1']}),
        ('tags', {'default': [True]}),
        ('tags', {'nullable': True}),
        ('mode', {'default': 'other'}),
        ('modes', {'default': ['fast', 'other']}),
        ('path', {'default': Path('data/input')}),
        ('path', {'choices': [1]}),
        ('path', {'default': 'data/other'}),
        ('optional', {'default': '1'}),
        ('optional', {'choices': [None, 1]}),
        ('ratio', {'choices': [1]}),
        ('ratio', {'choices': [1.0, float('nan')]}),
        ('ratio', {'choices': [1.0, float('-inf')]}),
        ('mode', {'choices': []}),
        ('mode', {'choices': 'fast'}),
        ('number', {'choices': [0, 1]}),
        ('number', {'required': True}),
        ('force', {'choices': [True, False]}),
        ('force', {'required': True, 'default': None}),
        ('force', {'action': 'value'}),
    ],
)
def test_registry_rejects_invalid_defaults_choices_and_actions(registry, dest, changes):
    spec = next(option for option in registry['commands'][0]['options'] if option['dest'] == dest)
    spec.update(changes)
    with pytest.raises(ValueError, match=dest):
        App.from_registry(registry)

def test_registry_rejects_invalid_positional_defaults(registry):
    registry['commands'][0]['arguments'][0]['default'] = None
    with pytest.raises(ValueError, match='files.*default'):
        App.from_registry(registry)

def test_registry_rejects_missing_default(registry):
    del registry['commands'][0]['options'][0]['default']
    with pytest.raises(ValueError, match='missing required fields'):
        App.from_registry(registry)

def test_required_placeholders_and_nullable_defaults_remain_valid(registry):
    app = App.from_registry(registry)
    with pytest.raises(UsageError, match='missing required option --required'):
        app.parse([])

    with pytest.raises(UsageError, match='missing required option --many'):
        app.parse(['--required=1'])

    parsed = app.parse(['--required=1', '--many=2', '--many=3'])
    assert parsed.kwargs['required'] == 1
    assert parsed.kwargs['many'] == [2, 3]
    assert parsed.kwargs['optional'] is None
    assert parsed.kwargs['files'] == []

def test_registry_tuple_defaults_become_isolated_lists(registry):
    specs = registry['commands'][0]['options']
    tags = next(option for option in specs if option['dest'] == 'tags')
    tags['default'] = (4, 5)
    registry['commands'][0]['arguments'][0]['default'] = ('data/first',)
    app = App.from_registry(registry)
    args = ['--required=1', '--many=2']
    parsed = app.parse(args)
    assert parsed.kwargs['tags'] == [4, 5]
    assert parsed.kwargs['files'] == [Path('data/first')]
    parsed.kwargs['tags'].append(6)
    parsed.kwargs['files'].clear()
    assert app.parse(args).kwargs['tags'] == [4, 5]
    assert app.parse(args).kwargs['files'] == [Path('data/first')]
    assert tags['default'] == (4, 5)
