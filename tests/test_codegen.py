import sys
import pytest
import random
from enum import Enum
from pathlib import Path
from subprocess import run
from types import ModuleType
from typing import Annotated
from importlib import import_module
from contextlib import contextmanager
from argly.codegen import generate, artifacts
from argly.helpgen import source, generate as generate_registry
from argly import App, Flag, Count, Range, group, Option, command, Argument, PathRule, Requires, Resource, Converter, Inherited, UsageError, MutuallyExclusive

class Color(Enum):
    RED = 'red'
    BLUE = 'blue'

CUSTOM_DEFAULT = {'value': 'default'}

def decode(value):
    return {'value': value}

def encode(value):
    return value['value']

@group('')
def root(*, verbose: Annotated[int, Count('-v', '/V')] = 0) -> None:
    pass

@command('run', rules=[Requires('number', 'label'), MutuallyExclusive('yes', 'no')])
def handler(
    paths: Annotated[list[Path], Argument()] = (Path('relative'),),
    *,
    verbose: Annotated[int, Inherited()],
    number: Annotated[int, Option('-n'), Range(1, 5)] = 2,
    label: Annotated[str, Option('-l', choices=('a', 'b'))] = 'a',
    color: Annotated[Color, Option()] = Color.RED,
    values: Annotated[list[int], Option()] = (1, 2),
    yes: Annotated[bool, Flag('-y')] = False,
    no: Annotated[bool, Flag()] = False,
    item: Annotated[dict, Option(), Converter(__name__ + ':decode', serializer=__name__ + ':encode')] = CUSTOM_DEFAULT,
) -> int:
    return verbose

@command('resources')
def resource_handler(z: Annotated[object, Resource('first')], a: Annotated[object, Resource('second')]) -> int:
    return 0

@command('path')
def path_handler(path: Annotated[Path, Argument(), PathRule(exists=True)] = Path('later')) -> int:
    return 0

@command('async')
async def async_handler(*, value: Annotated[int, Option()] = 5) -> int:
    return value

def prepared(app, directory):
    modules = {}
    for path, text in artifacts(app, directory / 'generated.py').items():
        if path.stem.endswith(('_runtime', '_metadata', '_help')):
            module = ModuleType(path.stem)
            exec(compile(text, str(path), 'exec'), module.__dict__)
            modules[path.stem.rsplit('_', 1)[1]] = module

    return App.from_generated(modules['runtime'], help_lookup=modules['help'].HELP.get, registry_loader=modules['metadata'].get_registry), modules

@pytest.fixture
def pair(tmp_path):
    direct = App('tool', [root, handler, resource_handler, path_handler, async_handler], windows_options=True)
    generated, _ = prepared(direct, tmp_path)
    return direct, generated

def outcome(app, args):
    try:
        invocation = app.parse(args)
        return invocation.path, invocation.values, invocation.kwargs, invocation.help_requested
    except UsageError as error:
        return error.to_dict()

@pytest.mark.parametrize('tokens', [
    [], ['--help'], ['run'], ['run', '-vyn3', '-lb'],
    ['/V', 'run', '--number=3', '--label=b', '--values=7', '--values=8'],
    ['run', '--number=3'], ['run', '--yes', '--no'],
    ['run', '--color=blu'], ['run', '--number=NaN'], ['run', '--number=6'],
    ['run', '--label=wrong'], ['run', '--unknown'], ['runn'],
    ['run', '--number', '--help'], ['run', '--', '--help'],
    ['run', '--item=hello', 'one', 'two'], ['run', '--help', 'ignored'],
])
def test_prepared_and_discovered_parsers_agree(pair, tokens):
    direct, generated = pair
    assert outcome(generated, tokens) == outcome(direct, tokens)

def test_random_invocations_have_identical_results_and_diagnostics(pair):
    direct, generated = pair
    randomizer = random.Random(45)
    tokens = ['-v', '-vv', '-y', '--no', '--number=4', '--number=-1', '--label=b', '--label=z', '--color=blue', '--color=bl', '--values=3', '--item=hello', '--help', '--', 'file', '-n', '2']
    for _ in range(400):
        args = ['run', *randomizer.choices(tokens, k=randomizer.randrange(9))]
        assert outcome(generated, args) == outcome(direct, args), args

def test_prepared_metadata_is_lazy_immutable_and_defaults_are_per_invocation(pair):
    direct, generated = pair
    assert generated._registry is None
    assert set(generated._nodes._cache) == {''}
    first = generated.parse(['run'])
    first.kwargs['values'].append(100)
    first.kwargs['item']['value'] = 'changed'
    first.kwargs['paths'].append(Path('changed'))
    assert generated.parse(['run']).kwargs == direct.parse(['run']).kwargs
    assert set(generated._nodes._cache) == {'', 'run'}
    with pytest.raises(TypeError):
        generated._nodes['run'].lookup['--number']['default'] = 99
    assert generated._registry is None
    assert generated.registry == direct.registry
    for output_format in ('markdown', 'man', 'json'):
        assert generated.export_docs(output_format) == direct.export_docs(output_format)
    for path in direct._nodes:
        assert generated.format_help(path) == direct.format_help(path)

def test_prepared_load_skips_registry_validation(tmp_path, monkeypatch):
    direct = App('tool', [root, handler])
    _, modules = prepared(direct, tmp_path)
    def reject(_):
        raise AssertionError('validated at runtime')
    monkeypatch.setattr('argly.app.validate_registry', reject)
    generated = App.from_generated(modules['runtime'], help_lookup=modules['help'].HELP.get, registry_loader=modules['metadata'].get_registry)
    assert generated.parse(['run']).kwargs['number'] == 2
    modules['runtime'].FORMAT_VERSION += 1
    with pytest.raises(ValueError, match='regenerate'):
        App.from_generated(modules['runtime'], help_lookup=modules['help'].HELP.get, registry_loader=modules['metadata'].get_registry)

def test_dynamic_path_checks_and_async_execution(pair, tmp_path, monkeypatch):
    direct, generated = pair
    monkeypatch.chdir(tmp_path)
    assert outcome(generated, ['path']) == outcome(direct, ['path'])
    (tmp_path / 'later').touch()
    assert generated.parse(['path']).kwargs == direct.parse(['path']).kwargs
    assert generated.run(['async']) == direct.run(['async']) == 5

def test_resource_order_survives_both_generation_formats(tmp_path):
    events = []
    def provider(name):
        @contextmanager
        def resource(_):
            events.append('enter ' + name)
            try:
                yield object()
            finally:
                events.append('exit ' + name)
        return resource
    resources = {'first': provider('first'), 'second': provider('second')}
    direct = App('tool', [resource_handler], resources=resources)
    namespace = {}
    exec(source(direct), namespace)
    legacy = App.from_registry(namespace['REGISTRY'], resources=resources)
    generated, _ = prepared(direct, tmp_path)
    generated._resources = resources
    for app in (direct, legacy, generated):
        events.clear()
        assert app.run(['resources']) == 0
        assert events == ['enter first', 'enter second', 'exit second', 'exit first']

def test_artifacts_are_stable_checked_together_and_published_entry_last(tmp_path, monkeypatch):
    app = App('tool', [root, handler])
    output = tmp_path / 'generated.py'
    assert not generate(app, output, check=True)
    assert not list(tmp_path.iterdir())
    assert generate(app, output)
    files = artifacts(app, output)
    assert list(files)[-1] == output
    before = {path: path.stat().st_mtime_ns for path in files}
    assert generate(app, output, check=True)
    assert generate(app, output)
    assert before == {path: path.stat().st_mtime_ns for path in files}
    help_file = next(path for path in files if path.stem.endswith('_help'))
    help_file.write_text('stale')
    assert not generate(app, output, check=True)
    assert help_file.read_text() == 'stale'
    assert generate(app, output)
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        module = import_module('generated')
        assert module.load().parse(['run']).kwargs == app.parse(['run']).kwargs
    finally:
        for path in files:
            sys.modules.pop(path.stem, None)

@pytest.mark.parametrize(('field', 'reference'), [('handler', 'missing_codegen_module:handler'), ('handler', 'builtins:None'), ('converter', 'builtins:None'), ('enum', 'builtins:str')])
def test_bad_references_fail_before_publishing(tmp_path, field, reference):
    app = App('tool', [root, handler])
    entry = app.registry['commands'][1]
    if field == 'handler':
        entry[field] = reference
    else:
        spec = next(spec for spec in entry['options'] if field in spec)
        spec[field] = reference
    with pytest.raises(ValueError):
        generate(app, tmp_path / 'generated.py')
    assert not list(tmp_path.iterdir())

def test_invalid_emitted_python_is_not_published(tmp_path, monkeypatch):
    app = App('tool', [resource_handler])
    monkeypatch.setattr('argly.codegen._runtime_source', lambda _: 'invalid python !')
    with pytest.raises(SyntaxError):
        generate(app, tmp_path / 'generated.py')
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr('argly.helpgen.source', lambda *args, **kwargs: 'invalid python !')
    with pytest.raises(SyntaxError):
        generate_registry(app, tmp_path / 'legacy.py')
    assert not list(tmp_path.iterdir())

def test_prepared_cli_and_runtime_imports(tmp_path):
    output = tmp_path / 'generated.py'
    args = [sys.executable, '-m', 'argly', 'gen', '--prepared', '--package', 'examples.remote_cli.commands', '--name', 'tool', '--output', str(output)]
    for extra, status in ((['--check'], 1), ([], 0), (['--check'], 0)):
        result = run([*args, *extra], capture_output=True, text=True)
        assert result.returncode == status, result.stderr
    script = '''
import sys
from generated import load
app = load()
assert app.parse(['remote', 'list']).kwargs == {'verbose': 0}
assert app._registry is None
assert 'argly.compiler' not in sys.modules
assert 'argly.codegen' not in sys.modules
assert 'argly.helpgen' not in sys.modules
assert not any(name.startswith('examples.remote_cli.commands') for name in sys.modules)
assert not any(name.endswith(('_metadata', '_help')) for name in sys.modules)
'''
    result = run([sys.executable, '-c', script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
