import sys
import json
import pytest
from pathlib import Path
from subprocess import run
from typing import Annotated
from argly import App, Flag, Range, group, Option, command, Argument, PathRule, Resource, AtLeastOne

@group('')
def root(*, verbose: Annotated[bool, Flag('-v')] = False) -> None:
    pass

@command('read', summary='Read a file.', rules=[AtLeastOne('path', 'number')])
def read(
    client: Annotated[object, Resource()],
    path: Annotated[Path, Argument(help='Input | file', metavar='FILE'), PathRule(kind='file')] = Path('input.txt'),
    *,
    number: Annotated[int, Option('-n'), Range(1, 5)] = 2,
) -> int:
    return 0

def test_json_description_is_complete_detached_and_stable():
    app = App('tool', [root, read])
    data = json.loads(app.export_docs('json', path='read'))
    assert data['schema_version'] == 1
    assert data['name'] == 'tool'
    assert len(data['commands']) == 1
    command_data = data['commands'][0]
    assert command_data['path'] == 'read'
    assert command_data['usage'] == 'Usage: tool read [options] [FILE]'
    assert [option['name'] for option in command_data['options']] == ['verbose', 'number']
    assert command_data['arguments'][0]['default'] == 'input.txt'
    assert command_data['arguments'][0]['constraints']['path']['kind'] == 'file'
    assert command_data['options'][1]['constraints'] == {'minimum': 1, 'maximum': 5}
    assert command_data['rules'] == [{'kind': 'at_least_one', 'parameters': ['path', 'number']}]
    assert 'client' not in app.export_docs('json')
    assert 'handler' not in command_data
    data['commands'][0]['options'][0]['default'] = True
    assert json.loads(app.export_docs('json', path='read'))['commands'][0]['options'][0]['default'] is False
    assert app.export_docs('json') == app.export_docs('json')

def test_markdown_and_man_include_inheritance_constraints_and_help():
    app = App('tool', [root, read])
    markdown = app.export_docs()
    assert '# tool command reference' in markdown
    assert '## tool read' in markdown
    assert 'Input \\| file' in markdown
    assert 'minimum: 1' in markdown
    assert 'must be a file' in markdown
    assert 'Supply at least one of: path, number' in markdown
    assert r'\-\-verbose' in markdown
    assert '--help' in markdown
    man = app.export_docs('man')
    assert man.startswith('.TH ')
    assert '.SS Synopsis' in man
    assert r'\-\-verbose' in man
    assert 'minimum: 1' in man

def test_format_escaping():
    @command('', summary='.SH INJECTED\n<script>alert(1)</script>\n`tick` \\backslash')
    def unusual(*, value: Annotated[str, Option(help='a | b\n.next')]) -> int:
        return 0

    app = App('tool', [unusual])
    markdown = app.export_docs()
    assert '<script>' not in markdown
    assert '&lt;script&gt;' in markdown
    assert r'\`tick\`' in markdown
    assert r'a \| b<br>\.next' in markdown
    man = app.export_docs('man')
    assert '\n.SH INJECTED\n' not in man
    assert '\n\\&.SH INJECTED\n' in man
    assert r'\ebackslash' in man

def test_documentation_never_imports_handlers_or_resources():
    script = '''
import sys
from examples.remote_cli.generated import load
app = load()
for format in ('markdown', 'man', 'json'):
    assert app.export_docs(format)
assert not any(name.startswith('examples.remote_cli.commands') for name in sys.modules)
assert 'argly.compiler' not in sys.modules
'''
    result = run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

@pytest.fixture
def legacy_registry(tmp_path):
    from argly.helpgen import generate

    app = App.discover('tool', 'examples.remote_cli.commands', windows_options=True)
    generate(app, tmp_path / 'example_registry.py')
    return tmp_path

@pytest.mark.parametrize('format', ['markdown', 'man', 'json'])
def test_cli_exports_and_checks_files(legacy_registry, format):
    tmp_path = legacy_registry
    output = tmp_path / 'output'
    args = [sys.executable, '-m', 'argly', 'docs', '--registry', 'example_registry', '--format', format, '--output', str(output)]
    for extra, expected in [(['--check'], 1), ([], 0), (['--check'], 0)]:
        result = run([*args, *extra], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == expected, result.stderr
    assert output.read_text(encoding='utf-8')
    output.write_text('stale')
    assert run([*args, '--check'], cwd=tmp_path, capture_output=True).returncode == 1

def test_cli_stdout_selected_command_and_invalid_options(legacy_registry):
    args = [sys.executable, '-m', 'argly', 'docs', '--registry', 'example_registry:REGISTRY', '--format', 'json', '--command', 'remote add']
    result = run(args, cwd=legacy_registry, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert [command['path'] for command in json.loads(result.stdout)['commands']] == ['remote add']
    assert run([*args, '--check'], cwd=legacy_registry, capture_output=True).returncode == 2
    app = App('tool', [read])
    with pytest.raises(ValueError, match='unknown command'):
        app.export_docs(path='missing')
    with pytest.raises(ValueError, match='unsupported documentation'):
        app.export_docs('html')

def test_docs_are_atomic_when_replace_fails(tmp_path, monkeypatch):
    from argly import helpgen

    output = tmp_path / 'manual.md'
    output.write_bytes(b'original')

    def fail(*_):
        raise OSError('failed replacement')

    monkeypatch.setattr(helpgen, 'replace', fail)
    with pytest.raises(OSError, match='replacement'):
        helpgen.write_output(output, b'new contents')
    assert output.read_bytes() == b'original'
    assert list(tmp_path.iterdir()) == [output]
