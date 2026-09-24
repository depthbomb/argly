import pytest
from os import name
from argly.helpgen import source
from typing import Annotated, Optional
from pathlib import Path, PurePosixPath
from argly import App, Option, Argument, UsageError, command

@command('')
def paths(
    output: Annotated[Path, Argument()] = Path('data/output.txt'),
    extra: Annotated[list[Path], Argument()] = (Path('data/extra.txt'),),
    *,
    config: Annotated[Path, Option(choices=['./settings/app.toml', 'settings/other.toml'])] = Path('settings/app.toml'),
    inputs: Annotated[list[Path], Option(choices=['data/first.txt', 'data/second.txt'])] = (Path('data/first.txt'),),
    optional: Annotated[Optional[Path], Option()] = None,
) -> int:
    return 0

def test_generated_paths_use_portable_separators_and_keep_path_types():
    namespace = {}
    exec(source(App('tool', [paths])), namespace)
    registry = namespace['REGISTRY']
    entry = registry['commands'][0]
    assert entry['arguments'][0]['default'] == 'data/output.txt'
    assert entry['arguments'][1]['default'] == ['data/extra.txt']
    assert entry['options'][0]['default'] == 'settings/app.toml'
    assert entry['options'][0]['choices'] == ['settings/app.toml', 'settings/other.toml']
    assert entry['options'][1]['default'] == ['data/first.txt']
    assert entry['options'][1]['choices'] == ['data/first.txt', 'data/second.txt']
    assert PurePosixPath(entry['arguments'][0]['default']).parts == ('data', 'output.txt')
    app = App.from_registry(registry)
    assert app.parse([]).kwargs == {
        'output': Path('data/output.txt'),
        'extra': [Path('data/extra.txt')],
        'config': Path('settings/app.toml'),
        'inputs': [Path('data/first.txt')],
        'optional': None,
    }

def test_portable_path_choices_load_and_match_native_input():
    registry = App('tool', [paths]).registry
    spec = registry['commands'][0]['options'][0]
    spec['default'] = 'settings/app.toml'
    spec['choices'] = ['settings/app.toml', 'settings/other.toml']
    app = App.from_registry(registry)
    parsed = app.parse([
        '--config=' + str(Path('settings/other.toml')),
        '--inputs=data/second.txt',
        '--inputs=./data/first.txt',
    ])
    assert parsed.kwargs['config'] == Path('settings/other.toml')
    assert parsed.kwargs['inputs'] == [Path('data/second.txt'), Path('data/first.txt')]
    with pytest.raises(UsageError, match='choose from'):
        app.parse(['--config=settings/missing.toml'])

@pytest.mark.skipif(name != 'nt', reason='Backslash-separated registries use Windows path semantics')
def test_existing_windows_path_metadata_still_loads():
    registry = App('tool', [paths]).registry
    spec = registry['commands'][0]['options'][0]
    spec['default'] = 'settings\\app.toml'
    spec['choices'] = ['settings\\app.toml', 'settings\\other.toml']
    app = App.from_registry(registry)
    assert app.parse([]).kwargs['config'] == Path('settings/app.toml')
    assert app.parse(['--config=settings/other.toml']).kwargs['config'] == Path('settings/other.toml')
