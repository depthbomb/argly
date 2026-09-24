import ast
import sys
import pytest
from pathlib import Path
from subprocess import run
from argly import App, command
from argly.helpgen import source, generate

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example():
    return App.discover('tool', 'examples.remote_cli.commands', windows_options=True)


def test_generated_help_matches_every_page_and_has_no_imports(example):
    generated = source(example)
    tree = ast.parse(generated)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    namespace = {}
    exec(compile(generated, 'generated.py', 'exec'), namespace)
    for entry in example.registry['commands']:
        assert namespace['get_help'](entry['path']) == example.format_help(entry['path'])

    assert namespace['get_help']('missing') is None
    assert namespace['REGISTRY'] == example.registry


def test_generation_is_stable_atomic_and_check_does_not_write(example, tmp_path):
    output = tmp_path / 'generated.py'
    assert not generate(example, output, check=True)
    assert not output.exists()
    assert generate(example, output)
    timestamp = output.stat().st_mtime_ns
    assert generate(example, output)
    assert output.stat().st_mtime_ns == timestamp
    assert generate(example, output, check=True)
    output.write_text('# stale\n', encoding='utf-8')
    assert not generate(example, output, check=True)
    assert output.read_text() == '# stale\n'
    assert generate(example, output)
    assert list(tmp_path.iterdir()) == [output]


def test_help_only_has_no_registry(example):
    assert 'REGISTRY' not in source(example, help_only=True)


def test_generated_help_does_not_import_command_modules_or_renderer():
    script = """
import sys
from argly import App
from examples.remote_cli.generated import REGISTRY, get_help
app = App.from_registry(REGISTRY, help_lookup=get_help)
assert app.run(['remote', 'add', '--help']) == 0
assert 'argly.compiler' not in sys.modules
assert 'argly.helpgen' not in sys.modules
assert not any(name.startswith('examples.remote_cli.commands') for name in sys.modules)
"""
    result = run([sys.executable, '-c', script], cwd=PROJECT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'Usage: tool remote add' in result.stdout


def test_related_commands_share_a_lazy_module_and_cache_handlers_separately():
    script = """
import sys
from argly import App
from examples.remote_cli.generated import REGISTRY, get_help
app = App.from_registry(REGISTRY, help_lookup=get_help)
assert app.parse(['remote', 'add', 'origin', '-uabc']).kwargs['url'] == 'abc'
assert not any(name.startswith('examples.remote_cli.commands') for name in sys.modules)
assert app.run(['remote', 'add', 'origin', '-uabc']) == 0
module = sys.modules['examples.remote_cli.commands.remote']
assert 'examples.remote_cli.commands.root' not in sys.modules
assert 'argly.compiler' not in sys.modules
assert app._handlers == {'remote add': module.add}
assert app.run(['remote', 'add', 'origin', '-uabc']) == 0
assert len(app._handlers) == 1
assert app.run(['remote', 'list', '-vv']) == 0
assert sys.modules['examples.remote_cli.commands.remote'] is module
assert app._handlers == {
    'remote add': module.add,
    'remote list': module.list_remotes,
}
"""
    result = run([sys.executable, '-c', script], cwd=PROJECT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count('name=origin') == 2
    assert result.stdout.count('No remotes configured (verbosity 2).') == 1


def test_cli_generate_check_and_staleness(tmp_path):
    output = tmp_path / 'help.py'
    args = [
        sys.executable,
        '-m',
        'argly',
        'gen',
        '--package',
        'examples.remote_cli.commands',
        '--name',
        'tool',
        '--output',
        str(output),
    ]
    for extra, code in [(['--check'], 1), ([], 0), (['--check'], 0)]:
        result = run([*args, *extra], cwd=PROJECT, capture_output=True, text=True)
        assert result.returncode == code, result.stderr

    output.write_text(output.read_text() + '# stale\n', encoding='utf-8')
    result = run([*args, '--check'], cwd=PROJECT, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'stale' in result.stderr


def test_strings_are_escaped_as_python_literals():
    @command('', summary='Quotes \' " and \\ slash\nUnicode cafÃ© ðŸš€\n\x00')
    def local() -> int:
        return 0

    app = App('tool', [local])
    namespace = {}
    exec(source(app, help_only=True), namespace)
    assert namespace['get_help']('') == app.format_help()
    with pytest.raises(ValueError, match='module-level'):
        source(app)


def test_committed_example_is_fresh(example):
    assert generate(example, PROJECT / 'examples/remote_cli/generated.py', check=True)


def test_console_entry_point_discovers_packages_from_working_directory(tmp_path):
    executable = Path(sys.executable).with_name('argly.exe' if sys.platform == 'win32' else 'argly')
    if not executable.exists():
        pytest.skip('console entry point requires an installed argly package')

    result = run(
        [
            str(executable),
            'gen',
            '--package',
            'examples.remote_cli.commands',
            '--name',
            'tool',
            '--output',
            str(tmp_path / 'generated.py'),
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'generated.py').exists()


@pytest.mark.parametrize(
    ('arguments', 'code', 'message'),
    [
        (['--help'], 0, 'gen'),
        (['gen', '--help'], 0, 'usage: argly gen'),
        ([], 2, 'command'),
        (['unknown'], 2, 'invalid choice'),
        (['gen'], 2, '--package'),
    ],
)
def test_cli_routing_and_help(arguments, code, message):
    result = run(
        [sys.executable, '-m', 'argly', *arguments],
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == code
    assert message in result.stdout + result.stderr
