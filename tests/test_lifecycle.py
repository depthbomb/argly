import sys
import pytest
import asyncio
from io import StringIO
from typing import Annotated
from importlib import import_module
from contextlib import contextmanager, asynccontextmanager
from argly import App, Option, command, Resource, UsageError

def test_async_handler_from_sync_and_async_entry_points():
    @command('')
    async def handler(*, count: Annotated[int, Option()] = 3) -> int:
        await asyncio.sleep(0)
        return count

    app = App('tool', [handler])
    assert app.run(['--count=4']) == 4
    assert asyncio.run(app.run_async(['--count=5'])) == 5

    async def existing_loop():
        with pytest.raises(RuntimeError, match='run_async'):
            app.run([])
        assert await app.run_async([]) == 3

    asyncio.run(existing_loop())

def test_sync_handler_works_in_async_entry_point():
    @command('')
    def handler() -> int:
        return 6

    assert asyncio.run(App('tool', [handler]).run_async([])) == 6

def test_resources_share_values_and_close_in_reverse_order():
    events = []

    @contextmanager
    def first(invocation):
        events.append(('open first', invocation.kwargs['count']))
        try:
            yield object()
        finally:
            events.append('close first')

    @asynccontextmanager
    async def second(invocation):
        events.append('open second')
        try:
            yield 'second'
        finally:
            events.append('close second')

    @command('')
    def handler(
        one: Annotated[object, Resource('first')],
        same: Annotated[object, Resource('first')],
        two: Annotated[str, Resource('second')],
        *,
        count: Annotated[int, Option()] = 7,
    ) -> int:
        assert one is same
        assert two == 'second'
        events.append('handler')
        return count

    app = App('tool', [handler], resources={'first': first, 'second': second})
    assert app.parse([]).kwargs == {'count': 7}
    assert events == []
    assert app.run([]) == 7
    assert events == [('open first', 7), 'open second', 'handler', 'close second', 'close first']

def test_resources_are_not_opened_for_help_or_errors():
    def provider(_):
        raise AssertionError('resource initialized')

    @command('')
    async def handler(client: Annotated[object, Resource()], *, value: Annotated[int, Option()]) -> int:
        raise AssertionError('handler executed')

    app = App('tool', [handler], resources={'client': provider})
    assert app.run(['--help'], out=StringIO()) == 0
    assert asyncio.run(app.run_async(['--value=no'], err=StringIO())) == 2

def test_cleanup_on_handler_exception_and_failed_acquisition():
    events = []

    @contextmanager
    def resource(_):
        events.append('open')
        try:
            yield 'resource'
        finally:
            events.append('close')

    @command('')
    def handler(value: Annotated[str, Resource()]) -> int:
        raise RuntimeError('handler failed')

    with pytest.raises(RuntimeError, match='handler failed'):
        App('tool', [handler], resources={'value': resource}).run([])
    assert events == ['open', 'close']

    events.clear()

    @command('')
    def missing(value: Annotated[str, Resource()], absent: Annotated[str, Resource()]) -> int:
        raise AssertionError('handler called with missing resource')

    with pytest.raises(ValueError, match='no resource provider'):
        App('tool', [missing], resources={'value': resource}).run([])
    assert events == ['open', 'close']

def test_async_cancellation_cleans_up():
    events = []

    async def exercise():
        started = asyncio.Event()

        @asynccontextmanager
        async def resource(_):
            events.append('open')
            try:
                yield object()
            finally:
                await asyncio.sleep(0)
                events.append('close')

        @command('')
        async def handler(value: Annotated[object, Resource()]) -> int:
            started.set()
            await asyncio.Event().wait()
            return 0

        app = App('tool', [handler], resources={'value': resource})
        task = asyncio.create_task(app.run_async([]))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert events == ['open', 'close']

def test_generated_async_handlers_and_resource_references_are_lazy(tmp_path, monkeypatch):
    (tmp_path / 'lazy_async_handler.py').write_text(
        'from typing import Annotated\nfrom argly import Resource, command\n'
        '@command("fetch")\nasync def fetch(client: Annotated[int, Resource()]) -> int:\n    return client\n'
    )
    (tmp_path / 'lazy_async_resource.py').write_text(
        'from contextlib import asynccontextmanager\n'
        '@asynccontextmanager\nasync def client(invocation):\n    yield 9\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        module = import_module('lazy_async_handler')
        registry = App('tool', [module.fetch]).registry
        sys.modules.pop('lazy_async_handler')
        app = App.from_registry(registry, resources={'client': 'lazy_async_resource:client'})
        app.format_help('fetch')
        assert app.parse(['fetch']).kwargs == {}
        assert 'lazy_async_handler' not in sys.modules
        assert 'lazy_async_resource' not in sys.modules
        assert app.run(['fetch']) == 9
    finally:
        sys.modules.pop('lazy_async_handler', None)
        sys.modules.pop('lazy_async_resource', None)

def test_async_usage_errors_are_rendered_after_cleanup():
    events = []

    @contextmanager
    def resource(_):
        try:
            yield 1
        finally:
            events.append('closed')

    @command('fetch')
    async def handler(value: Annotated[int, Resource()]) -> int:
        raise UsageError('bad request', code='bad_request')

    err = StringIO()
    assert asyncio.run(App('tool', [handler], resources={'value': resource}).run_async(['fetch'], err=err)) == 2
    assert events == ['closed']
    assert 'Usage: tool fetch' in err.getvalue()

def test_invalid_async_return_and_resource_defaults():
    @command('')
    async def handler() -> int:
        return True

    with pytest.raises(TypeError, match='must return an int'):
        App('tool', [handler]).run([])

    @command('')
    def bad(value: Annotated[str, Resource()] = 'bad') -> int:
        return 0

    with pytest.raises(ValueError, match='cannot have defaults'):
        App('tool', [bad])
