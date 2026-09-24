# argly

Argly turns annotated Python functions into command-line tools. Keep related commands in the same module, share options through groups, and generate the parser data and help ahead of time so startup has less work to do.

Requires Python 3.14 or newer. The pure Python package has no runtime dependencies.

With a virtual environment activated:

```sh
python -m pip install argly
```

From a checkout, with your virtual environment activated:

```sh
python -m pip install -e ".[dev]"
python -m examples.remote_cli --help
python -m examples.remote_cli -v remote add origin --url=https://example.com -fvv
```

The example just prints the parsed values. Its [remote commands](examples/remote_cli/commands/remote.py) live together in one file, with [global options](examples/remote_cli/commands/root.py) in another. It includes prepared artifacts, so you can run it straight from a checkout.

## Commands are functions

Here's what a command module could look like. Put this in `mycli/commands/remote.py`, with an `__init__.py` in each package directory:

```python
from typing import Annotated
from argly import Flag, Count, group, Option, command, Argument, Inherited

@group('remote', summary='Manage remotes.')
def remote(*, verbose: Annotated[int, Count('-v')] = 0) -> None:
    pass

@command('remote add', summary='Add a remote.')
def add(
    name: Annotated[str, Argument()],
    *,
    url: Annotated[str, Option('-u')],
    verbose: Annotated[int, Inherited()],
    force: Annotated[bool, Flag('-f')] = False,
) -> int:
    print(f'Adding {name}: {url}, force={force}, verbosity={verbose}')

    return 0

@command('remote list', summary='List remotes.')
def list_remotes(*, verbose: Annotated[int, Inherited()]) -> int:
    print(f'Listing remotes at verbosity {verbose}')

    return 0
```

Parameter names become long options, so `url` gives you `--url`, and `-u` is its alias. Value options and positional arguments without defaults are required. Commands return an integer exit code, and the decorators leave them callable as ordinary Python functions.

A group declares options for its descendants; its function doesn't run. `Inherited()` passes an ancestor's option into a handler without repeating its definition or default. In this example, `remote -vv add ...` and `remote add ... -vv` both work.

Use `@group('')` for global options that can appear anywhere before `--`. Other group options become available after entering that group. Command paths define the nesting, so related handlers can share a file without having to mirror the hierarchy in folders.

## Familiar option syntax

Long names, short aliases, combined flags, and counters all work:

```text
--url example.com     --url=example.com
-u example.com       -uexample.com       -u=example.com
-abc                 -vvv
```

In a short-option cluster, an option that takes a value consumes the rest of the token or the next argument. Use `--` when the remaining arguments should be treated literally.

Windows-style aliases are opt-in: declare something like `Option('-u', '/URL', '/U')` and enable `windows_options=True`, or use the generator's `--windows-options` switch. Matching is exact and case-sensitive, so an unregistered path like `/tmp` stays a value.

## Generate once, load what's needed

From the directory containing `mycli`, generate a prepared entry point:

```sh
argly gen --prepared --package mycli.commands --name mycli --output mycli/generated.py
```

Then use it in `mycli/__main__.py`:

```python
from mycli.generated import main

raise SystemExit(main())
```

Now you can run `python -m mycli remote add origin -u example.com`.

Generation imports your declarations, checks handler and converter references, and prepares option lookups, defaults, parameter bindings, and validation code. Put handlers, enum types, and converter callbacks in importable modules. Generated references can't point at local definitions or `__main__`.

The output includes `generated.py` and three `_generated_*` sibling modules for runtime data, help, and declaration metadata. Ship them together. The loader skips registry copying and validation, and creates command nodes as they're needed. Help and documentation data stay separate from the parsing path.

The generated `main()` serves requests like `mycli remote add --help` directly from saved text, without importing argly or your command modules. More involved argument lists go through the parser. Handler imports happen when a command runs; enums and custom converters can import their own modules during parsing.

Regenerate after changing declarations or upgrading argly. Generated runtime formats are versioned, and incompatible artifacts ask you to regenerate. Add `--check` to the same command in CI to check every artifact without rewriting it:

```sh
argly gen --prepared --package mycli.commands --name mycli --output mycli/generated.py --check
```

The sibling names change when their contents change. Older siblings are left in place for processes still using them; package the files from a fresh generation. `python -m argly gen` works too.

If you want an `App` instance for repeated parsing or custom setup, import `load` from the generated module and call `load()`. The generated module also exports `get_registry()`, which loads a fresh copy of the declaration metadata on demand.

The single-file registry format is still available: omit `--prepared` to generate `REGISTRY` and `get_help`, then load them with `App.from_registry(REGISTRY, help_lookup=get_help)`. `--help-only` emits just the saved help text.

While experimenting, you can skip generation and use `App.discover('mycli', 'mycli.commands').run()`. That imports the command modules up front.

## Types and validation

Use `str`, `int`, `float`, `Path`, `UUID`, `date`, or `datetime` for values. `Flag()` handles booleans, and `Count()` handles integer counters. `Literal[...]`, enum annotations, and `Option(choices=...)` restrict accepted values. Enums use their values on the command line and give your handler enum members.

A `list[T]` option collects repeated values. A final `list[T]` positional collects the remaining positional arguments. Use `T | None` with a `None` default for a value that can be omitted. Mutable defaults are kept separate between invocations.

Constraints go alongside the CLI marker in `Annotated`. For example, this could live in `mycli/commands/scan.py`:

```python
from pathlib import Path
from typing import Annotated
from argly import Flag, Range, Option, command, Argument, PathRule, MutuallyExclusive

@command('scan', rules=[MutuallyExclusive('quiet', 'verbose')])
def scan(
    path: Annotated[Path, Argument(), PathRule(kind='file', readable=True)],
    *,
    limit: Annotated[int, Option(), Range(1, 100)] = 20,
    quiet: Annotated[bool, Flag('-q')] = False,
    verbose: Annotated[bool, Flag('-v')] = False,
) -> int:
    print(f'Scanning {path}, limit={limit}, quiet={quiet}, verbose={verbose}')

    return 0
```

Ranges are inclusive. `PathRule` supports `exists`, `kind='file'` or `'directory'`, `readable`, and `writable`. Filesystem checks happen when values are parsed, including defaults, so changes on disk are picked up between invocations.

Command and group rules refer to parameter names, including inherited options:

| Rule | What it checks |
| --- | --- |
| `MutuallyExclusive('quiet', 'verbose')` | At most one is supplied. |
| `AtLeastOne('file', 'url')` | At least one is supplied. |
| `Requires('token', 'user')` | Supplying `token` also requires `user`. |

These rules look at what the user explicitly supplied. Defaults don't count as supplied values.

For your own types, add `Converter('mycli.values:parse_size')` alongside `Option()` or `Argument()`. The callable receives a string; raise `ValueError` for invalid input. Add `serializer='mycli.values:format_size'` when using concrete defaults or choices. The serializer must return text your parser can read. Custom conversions still happen at parse time, even with prepared generation.

## Parse without running a handler

`App.parse()` takes an explicit argument list and returns an `Invocation`. It doesn't run handlers or print anything:

```python
from argly import UsageError
from mycli.generated import load

app = load()
try:
    invocation = app.parse(['remote', 'add', 'origin', '-u', 'example.com'])
    print(invocation.path)
    print(invocation.kwargs)
except UsageError as error:
    print(error.to_dict())
```

`invocation.values` contains all parsed CLI values; `kwargs` contains the values bound to the handler's parameters. Resource values are injected later, when the handler runs. `help_requested` tells you whether help was requested.

Usage errors expose `code`, `command`, `parameter`, `value`, and `suggestions`, plus a readable message. Suggestions are hints; they don't change the input. `App.run()` prints usage errors and returns `2`, returns `0` for help, and otherwise returns the handler's integer status. Override `App.format_error()` if you want a different presentation.

## Async handlers and shared resources

Handlers can be ordinary functions or `async def` functions. Both declare `-> int`. `App.run()` starts an event loop when the selected command needs one. If you're already inside an event loop, use `await app.run_async(args)` for async handlers or managed resources.

`Resource()` supplies a value from a context manager instead of reading it from the command line. Here's a file-writing command for `mycli/commands/files.py`:

```python
from collections.abc import Iterator
from typing import TextIO, Annotated
from contextlib import contextmanager
from argly import Option, command, Resource, Invocation

@contextmanager
def output_file(invocation: Invocation) -> Iterator[TextIO]:
    with open(invocation.kwargs['destination'], 'w', encoding='utf-8') as stream:
        yield stream

@command('write')
def write(
    output: Annotated[TextIO, Resource()],
    *,
    destination: Annotated[str, Option()],
) -> int:
    output.write('Hello!\n')

    return 0
```

After regenerating, register the provider in `mycli/__main__.py`:

```python
from mycli.generated import main

raise SystemExit(main(resources={'output': 'mycli.commands.files:output_file'}))
```

Now `python -m mycli write --destination hello.txt` opens the file, runs the handler, and closes the file. Providers receive the parsed `Invocation` and can return sync or async context managers, or awaitables that produce them. You can register a callable directly or use a `module:attribute` string to defer its import.

Parameters sharing a resource name receive the same value within an invocation. Resources are acquired in declaration order and closed in reverse order, including after exceptions or cancellation. Help and parsing alone don't open them.

## Export command documentation

The same metadata can produce Markdown, section-1 man pages, or JSON without importing command handlers:

```python
from pathlib import Path
from mycli.generated import load

app = load()
Path('commands.md').write_text(app.export_docs('markdown'), encoding='utf-8')
```

Use `'man'` or `'json'` for the other formats, or pass `path='remote add'` to select one command. JSON includes a `schema_version` and describes commands, options, arguments, defaults, and constraints.

The `argly docs` command reads the single-file registry format. To use it alongside a prepared application, generate a registry for documentation:

```sh
argly gen --package mycli.commands --name mycli --output mycli/registry.py
argly docs --registry mycli.registry --format markdown --output commands.md
argly docs --registry mycli.registry --format markdown --output commands.md --check
```

Use `--format man` or `--format json` for the other formats, and `--command "remote add"` to select a command. `--check` reports missing or stale output without changing it.

## Performance and development

Prepared generation moves discovery, schema validation, and parser-table setup out of application startup. It also emits conversion and validation functions for your declarations. Reuse a loaded `App` when parsing more than once.

Larger command trees have more startup work to save. Small tools may spend most of their startup time launching Python. The [benchmark script](benchmarks/bench.py) compares equivalent warm parses with `argparse` and reports help lookup and prepared versus discovered app loading separately. Its startup timers begin inside fresh Python processes, so they don't include interpreter launch time.

With the development dependencies installed:

```sh
python -m pytest --import-mode=importlib --cov=argly --cov-branch
python -m ruff check .
python -m mypy
python -m build --outdir dist/release
python -m twine check --strict dist/release/*
python benchmarks/bench.py
```

The release artifacts go in `dist/release` to keep them separate from local native builds.

There's also an optional Cython build of the same parser. To build a native wheel in PowerShell, with a C compiler installed:

```powershell
python -m pip install -e ".[dev,cython]"
$env:ARGLY_CYTHON = '1'
python -m build --wheel --no-isolation
Remove-Item Env:\ARGLY_CYTHON
```

The native wheel is written to `dist`; install it to use the compiled parser. Regular builds use pure Python. Prepared generation works with either build.
