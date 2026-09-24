import pytest
from io import StringIO
from pathlib import Path
from itertools import permutations
from typing import Literal, Optional, Annotated
from argly import App, Flag, Count, group, Option, command, Argument, Inherited, UsageError


@group('')
def root(*, verbose: Annotated[int, Count('-v', '/V')] = 0) -> None:
    pass


@group('remote')
def remote(*, token: Annotated[Optional[str], Option('-t', '/Token')] = None) -> None:
    pass


@command('remote add')
def add(
    name: Annotated[str, Argument()],
    *,
    url: Annotated[str, Option('-u', '/Option', '/O', '/o')],
    verbose: Annotated[int, Inherited()],
    auth: Annotated[Optional[str], Inherited('token')],
    force: Annotated[bool, Flag('-f')] = False,
    quiet: Annotated[bool, Flag('-q')] = False,
    color: Annotated[bool, Flag('-c')] = True,
) -> int:
    return verbose


@command('remote show')
def show(*, verbose: Annotated[int, Inherited()]) -> int:
    return verbose


@pytest.fixture(params=['discovered', 'generated'])
def app(request, tmp_path):
    app = App('tool', [root, remote, add, show], windows_options=True)
    if request.param == 'generated':
        from test_codegen import prepared

        app, _ = prepared(app, tmp_path)
    return app


@pytest.mark.parametrize(
    'tokens',
    [
        ['--url', 'abc'],
        ['--url=abc'],
        ['-u', 'abc'],
        ['-uabc'],
        ['-u=abc'],
        ['/Option', 'abc'],
        ['/Option=abc'],
        ['/O', 'abc'],
        ['/o=abc'],
    ],
)
def test_value_spellings(app, tokens):
    parsed = app.parse(['remote', 'add', 'origin', *tokens])
    assert parsed.kwargs == {
        'name': 'origin',
        'url': 'abc',
        'verbose': 0,
        'auth': None,
        'force': False,
        'quiet': False,
        'color': True,
    }


@pytest.mark.parametrize(
    'tokens',
    [
        ['-fqcvvv', '-uabc'],
        ['-f', '-q', '-c', '-vvv', '--url=abc'],
        ['-fqcvvvuabc'],
        ['-fqcvvvu=abc'],
    ],
)
def test_clusters_count_and_value_termination(app, tokens):
    parsed = app.parse(['remote', 'add', 'origin', *tokens])
    assert parsed.kwargs['verbose'] == 3
    assert parsed.kwargs['force'] is True
    assert parsed.kwargs['quiet'] is True
    assert parsed.kwargs['color'] is False
    assert parsed.kwargs['url'] == 'abc'


@pytest.mark.parametrize('index', range(7))
def test_global_option_anywhere_except_inside_an_option_value(app, index):
    tokens = ['remote', '--token=x', 'add', 'origin', '--url=abc', '-f']
    tokens.insert(index, '-vv')
    assert app.parse(tokens).kwargs['verbose'] == 2


@pytest.mark.parametrize(
    'tokens',
    [
        ['remote', '--token=abc', 'add', 'origin', '-uurl'],
        ['remote', 'add', '--token=abc', 'origin', '-uurl'],
        ['remote', 'add', 'origin', '-uurl', '--token=abc'],
    ],
)
def test_parent_option_inheritance_and_parameter_rename(app, tokens):
    parsed = app.parse(tokens)
    assert parsed.kwargs['auth'] == 'abc'
    assert parsed.values['token'] == 'abc'
    assert 'token' not in parsed.kwargs


def test_global_counts_accumulate_across_scopes(app):
    assert app.run(['-v', 'remote', '-v', 'add', 'origin', '-uabc', '-v']) == 3


@pytest.mark.parametrize(
    'tokens, message',
    [
        (['--token=x', 'remote', 'show'], 'unknown option'),
        (['remote', '--url=x', 'add'], 'unknown option'),
        (['remote', 'show', '--url=x'], 'unknown option'),
        (['remote', 'add', 'origin'], 'missing required option'),
        (['remote', 'add', '--url=x'], 'missing required argument'),
        (['remote', 'add', 'origin', '--url'], 'requires a value'),
        (['remote', 'add', 'origin', '--url', '-f'], 'requires a value'),
        (['remote', 'add', 'origin', '--url', '--'], 'requires a value'),
        (['remote', 'add', 'origin', '--force=yes'], 'does not take a value'),
        (['remote', 'add', 'origin', '--verbose=3'], 'does not take a value'),
        (['remote', 'add', 'origin', '-uabc', '-fx'], 'unknown option'),
        (['remote', 'bogus'], 'unknown command'),
        (['remote', 'show', 'extra'], 'unexpected argument'),
        (['remote', 'add', 'origin', '-uabc', '--ur=x'], 'unknown option'),
    ],
)
def test_usage_errors(app, tokens, message):
    with pytest.raises(UsageError, match=message):
        app.parse(tokens)

    output, errors = StringIO(), StringIO()
    assert app.run(tokens, out=output, err=errors) == 2
    assert message in errors.getvalue()
    assert output.getvalue() == ''


@pytest.mark.parametrize('value', ['', '-f', 'a=b=c', '--', 'remote'])
def test_explicit_values(app, value):
    assert app.parse(['remote', 'add', 'origin', '--url=' + value]).kwargs['url'] == value


@pytest.mark.parametrize('name', ['/tmp', '/OPTION', '-v', '--help', 'add', ''])
def test_end_of_options_makes_everything_literal(app, name):
    parsed = app.parse(['remote', 'add', '-uabc', '--', name])
    assert parsed.kwargs['name'] == name
    assert parsed.kwargs['verbose'] == 0
    assert not parsed.help_requested


def test_windows_names_are_exact_and_opt_in(app):
    assert app.parse(['remote', 'add', '/tmp', '-uabc']).kwargs['name'] == '/tmp'
    assert app.parse(['remote', 'add', '/OPTION', '-uabc']).kwargs['name'] == '/OPTION'
    unix = App('tool', [root, remote, add])
    assert unix.parse(['remote', 'add', '/O', '-uabc']).kwargs['name'] == '/O'


@pytest.mark.parametrize(
    'tokens',
    [
        ['remote', 'add', '--help'],
        ['--help', 'remote', 'add'],
        ['remote', '-h', 'add'],
        ['remote', 'add', '-vvh'],
    ],
)
def test_help_skips_required_values(app, tokens):
    output = StringIO()
    assert app.run(tokens, out=output) == 0
    assert output.getvalue().startswith('Usage: tool remote add')
    assert '--verbose' in output.getvalue()
    assert '--token' in output.getvalue()


def test_group_help_and_stdout_capture(app, capsys):
    assert app.run(['remote']) == 0
    assert 'Commands:' in capsys.readouterr().out


def test_option_order_and_repeated_parse_isolation(app):
    for parts in permutations(['-v', '-f', '--token=x', '--url=y']):
        parsed = app.parse(['remote', 'add', 'origin', *parts])
        assert parsed.kwargs['verbose'] == 1
        assert parsed.kwargs['url'] == 'y'

    assert app.parse(['remote', 'show']).kwargs == {'verbose': 0}
    assert app.parse(['remote', 'add', 'origin', '--url=a', '--url=b']).kwargs['url'] == 'b'


def test_typed_values_and_negative_positionals():
    @command('')
    def values(
        number: Annotated[int, Argument()],
        *,
        ratio: Annotated[float, Option('-r')],
        mode: Annotated[Literal['fast', 'slow'], Option()] = 'fast',
        file: Annotated[Path, Option()] = Path('default.txt'),
        extra: Annotated[Optional[int], Option()] = None,
    ) -> int:
        return number

    app = App('values', [values])
    parsed = app.parse(['-12', '-r', '-0.5', '--extra=4', '--file=a.txt'])
    assert parsed.kwargs == {
        'number': -12,
        'ratio': -0.5,
        'mode': 'fast',
        'file': Path('a.txt'),
        'extra': 4,
    }
    assert app.parse(['2', '--ratio=1']).kwargs['file'] == Path('default.txt')
    for tokens in (['x', '-r1'], ['2', '-rx'], ['2', '-r1', '--mode=other']):
        with pytest.raises(UsageError):
            app.parse(tokens)


def test_repeated_options_and_variadic_arguments():
    @command('')
    def values(
        paths: Annotated[list[Path], Argument()],
        *,
        tag: Annotated[list[str], Option('-t')] = ['default'],  # noqa: B006
    ) -> int:
        return len(paths)

    app = App('values', [values])
    parsed = app.parse(['a', '-tx', 'b', '-t', 'y'])
    assert parsed.kwargs == {'paths': [Path('a'), Path('b')], 'tag': ['x', 'y']}
    parsed = app.parse(['a'])
    parsed.kwargs['tag'].append('mutation')
    assert app.parse(['b']).kwargs['tag'] == ['default']
    with pytest.raises(UsageError, match='missing required argument'):
        app.parse([])


def test_ancestor_required_option_even_when_handler_does_not_bind_it():
    @group('')
    def required(*, token: Annotated[str, Option()]) -> None:
        pass

    @command('child')
    def child() -> int:
        return 8

    app = App('tool', [required, child])
    assert app.run(['child', '--token=x']) == 8
    with pytest.raises(UsageError, match='missing required option'):
        app.parse(['child'])


@pytest.mark.parametrize('result', [None, True, '0', 1.5])
def test_noninteger_handler_result_is_a_programming_error(result):
    @command('')
    def invalid() -> int:
        return result

    with pytest.raises(TypeError, match='must return an int'):
        App('tool', [invalid]).run([])


def test_handler_exceptions_are_not_swallowed():
    @command('')
    def invalid() -> int:
        raise RuntimeError('broken handler')

    with pytest.raises(RuntimeError, match='broken handler'):
        App('tool', [invalid]).run([])


def test_decorators_preserve_direct_calls():
    assert add('origin', url='example', verbose=7, auth=None) == 7


def test_path_choices_and_list_defaults():
    @command('')
    def files(
        *,
        file: Annotated[Path, Option(choices=['./allowed.txt', 'other.txt'])] = Path('allowed.txt'),
        paths: Annotated[list[Path], Option()] = [Path('first')],  # noqa: B006
    ) -> int:
        return 0

    app = App('tool', [files])
    assert app.parse(['--file=./allowed.txt']).kwargs['file'] == Path('allowed.txt')
    assert app.parse([]).kwargs['paths'] == [Path('first')]
    with pytest.raises(UsageError, match='choose from'):
        app.parse(['--file=forbidden'])


def test_optional_and_empty_variadic_positionals():
    @command('')
    def run(
        name: Annotated[str, Argument()] = 'default',
        files: Annotated[list[str], Argument()] = [],  # noqa: B006
    ) -> int:
        return 0

    app = App('tool', [run])
    assert app.parse([]).kwargs == {'name': 'default', 'files': []}
    assert app.parse(['name', 'a', 'b']).kwargs == {'name': 'name', 'files': ['a', 'b']}


def test_windows_value_does_not_consume_a_registered_option(app):
    with pytest.raises(UsageError, match='requires a value'):
        app.parse(['remote', 'add', 'origin', '-u', '/O'])

    assert app.parse(['remote', 'add', 'origin', '-u', '/tmp']).kwargs['url'] == '/tmp'


def test_default_flag_and_counter_without_python_defaults():
    @command('')
    def run(*, force: Annotated[bool, Flag()], verbose: Annotated[int, Count()]) -> int:
        return verbose

    assert App('tool', [run]).parse([]).kwargs == {'force': False, 'verbose': 0}

def test_factory_commands_dispatch_distinct_closures():
    def factory(path, code):
        @command(path)
        def handler() -> int:
            return code

        return handler

    first = factory('first', 11)
    second = factory('second', 22)
    assert first.__qualname__ == second.__qualname__
    app = App('tool', [first, second])
    assert app.run(['first']) == 11
    assert app.run(['second']) == 22
    assert app.run(['first']) == 11

def test_inherited_list_overrides_and_defaults_remain_isolated():
    @group('')
    def root(*, tag: Annotated[list[str], Option('-t')] = ('default',)) -> None:
        pass

    @command('child')
    def child(*, tag: Annotated[list[str], Inherited()]) -> int:
        return len(tag)

    app = App('tool', [root, child])
    parsed = app.parse(['-tbefore', 'child', '-tafter'])
    assert parsed.kwargs['tag'] == ['before', 'after']
    parsed.kwargs['tag'].append('mutation')
    assert app.parse(['child', '-tnext']).kwargs['tag'] == ['next']
    fallback = app.parse(['child'])
    assert fallback.kwargs['tag'] == ['default']
    fallback.kwargs['tag'].clear()
    assert app.parse(['child']).kwargs['tag'] == ['default']
