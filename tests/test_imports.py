import sys
from subprocess import run

def test_public_exports_and_annotations_resolve_in_a_fresh_process():
    script = '''
import argly
namespace = {}
exec('from argly import *', namespace)
assert set(namespace) - {'__builtins__'} == set(argly.__all__)
for name in argly.__all__:
    assert namespace[name] is getattr(argly, name)
    assert callable(namespace[name])

from typing import get_type_hints
from argly.app import App, Invocation
from argly._parser import UsageError, ParseResult
assert argly.App is App
assert argly.Invocation is Invocation
assert argly.UsageError is UsageError
assert get_type_hints(App.from_registry)['return'] is App
assert get_type_hints(Invocation.__init__)['result'] is ParseResult
assert get_type_hints(UsageError.__init__)['message'] is str
assert '_nodes' in get_type_hints(App)
'''
    result = run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
