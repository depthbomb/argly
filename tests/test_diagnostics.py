import sys
import json
import pytest
from io import StringIO
from subprocess import run
from typing import Literal, Annotated
from argly import App, Flag, Range, Option, command, Argument, UsageError

@command('remote add')
def add(
    name: Annotated[str, Argument()],
    *,
    url: Annotated[str, Option('-u')],
    count: Annotated[int, Option(), Range(1, 5)] = 1,
    mode: Annotated[Literal['fast', 'slow'], Option()] = 'fast',
    force: Annotated[bool, Flag('-f')] = False,
) -> int:
    return 0

@pytest.mark.parametrize('tokens,code,parameter,value', [
    (['remote', 'add', '--urll=x'], 'unknown_option', '--urll', '--urll=x'),
    (['remote', 'add', '--url'], 'missing_value', 'url', None),
    (['remote', 'add', '--force=yes'], 'unexpected_value', 'force', 'yes'),
    (['remote', 'add'], 'missing_option', 'url', None),
    (['remote', 'add', '--url=x'], 'missing_argument', 'name', None),
    (['remote', 'add', 'origin', '-ux', '--count=no'], 'invalid_value', 'count', 'no'),
    (['remote', 'add', 'origin', '-ux', '--count=6'], 'constraint', 'count', '6'),
    (['remote', 'add', 'origin', '-ux', '--mode=fas'], 'invalid_choice', 'mode', 'fas'),
    (['remote', 'add', 'origin', '-ux', 'extra'], 'unexpected_argument', None, 'extra'),
])
def test_structured_failures(tokens, code, parameter, value):
    app = App('tool', [add])
    with pytest.raises(UsageError) as caught:
        app.parse(tokens)
    error = caught.value
    assert error.code == code
    assert error.command == 'remote add'
    assert error.parameter == parameter
    assert error.value == value
    assert json.loads(json.dumps(error.to_dict())) == error.to_dict()
    assert error.to_dict()['message'] == str(error)

def test_command_and_option_suggestions_do_not_execute():
    app = App('tool', [add])
    with pytest.raises(UsageError) as caught:
        app.parse(['remote', 'ad'])
    assert caught.value.command == 'remote'
    assert caught.value.code == 'unknown_command'
    assert caught.value.suggestions == ('add',)
    with pytest.raises(UsageError) as caught:
        app.parse(['remote', 'add', '--urll=x'])
    assert '--url' in caught.value.suggestions

def test_errors_show_relevant_usage_on_stderr():
    app = App('tool', [add])
    out, err = StringIO(), StringIO()
    assert app.run(['remote', 'add', '--urll=x'], out=out, err=err) == 2
    assert out.getvalue() == ''
    assert err.getvalue().startswith('Usage: tool remote add')
    assert 'Did you mean: --url?' in err.getvalue()

def test_error_formatting_can_be_overridden():
    class JsonApp(App):
        def format_error(self, error):
            return json.dumps(error.to_dict()) + '\n'

    err = StringIO()
    app = JsonApp('tool', [add])
    assert app.run(['missing'], err=err) == 2
    assert json.loads(err.getvalue())['code'] == 'unknown_command'

def test_empty_custom_help_does_not_break_errors():
    app = App('tool', [add], help_lookup=lambda _: '')
    assert app.run(['missing'], err=StringIO()) == 2

def test_error_help_and_suggestions_do_not_import_handlers():
    script = '''
import sys
from io import StringIO
from examples.remote_cli.generated import load
app = load()
assert 'difflib' not in sys.modules
assert app.parse(['remote', 'list']).path == 'remote list'
assert 'difflib' not in sys.modules
assert app.run(['remote', 'ad'], err=StringIO()) == 2
assert not any(name.startswith('examples.remote_cli.commands') for name in sys.modules)
'''
    result = run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

def test_path_diagnostics_keep_the_original_input():
    from pathlib import Path

    @command('')
    def handler(*, file: Annotated[Path, Option(choices=['accepted.txt'])]) -> int:
        return 0

    with pytest.raises(UsageError) as caught:
        App('tool', [handler]).parse(['--file=./wrong.txt'])
    assert caught.value.code == 'invalid_choice'
    assert caught.value.value == './wrong.txt'
