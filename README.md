# argly

```sh
python -m pip install argly
```

From a checkout, with your virtual environment activated:

```sh
python -m pip install -e ".[dev]"
python -m examples.remote_cli --help
python -m examples.remote_cli -v remote add origin --url=https://example.com -fvv
```

The example just prints the parsed values. Its [remote commands](examples/remote_cli/commands/remote.py) live together in one file, with [global options](examples/remote_cli/commands/root.py) in another.

## Commands are functions

Here's what a command module could look like. Put this in `mycli/commands/remote.py`, with an `__init__.py` in each package directory:

```python
from typing import Annotated
from argly import Flag, Count, Option, Argument, Inherited, group, command


@group("remote", summary="Manage remotes.")
def remote(*, verbose: Annotated[int, Count("-v")] = 0) -> None:
    pass


@command("remote add", summary="Add a remote.")
def add(
    name: Annotated[str, Argument()],
    *,
    url: Annotated[str, Option("-u")],
    verbose: Annotated[int, Inherited()],
    force: Annotated[bool, Flag("-f")] = False,
) -> int:
    print(f"Adding {name}: {url}, force={force}, verbosity={verbose}")

    return 0


@command("remote list", summary="List remotes.")
def list_remotes(*, verbose: Annotated[int, Inherited()]) -> int:
    print(f"Listing remotes at verbosity {verbose}")

    return 0
```

Parameter names become long options, so `url` gives you `--url`, and `-u` is its alias. Value options and positional arguments without defaults are required. Commands return an integer exit code, and the decorators leave them callable as ordinary Python functions.

A group declares options for its descendants; its function doesn't run. `Inherited()` passes an ancestor's option into a handler without repeating its definition or default. In this example, `remote -vv add ...` and `remote add ... -vv` both work.

Use `@group("")` for global options that can appear anywhere before `--`. Other group options become available after entering that group. Command paths define the nesting, so related handlers can share a file without having to mirror the hierarchy in folders.

## Familiar option syntax

Long names, short aliases, combined flags, and counters all work:

```text
--url example.com     --url=example.com
-u example.com       -uexample.com       -u=example.com
-abc                 -vvv
```

In a short-option cluster, an option that takes a value consumes the rest of the token or the next argument. Use `--` when the remaining arguments should be treated literally.

Windows-style aliases are opt-in: declare something like `Option("-u", "/URL", "/U")` and enable `windows_options=True`, or use the generator's `--windows-options` switch. Matching is exact and case-sensitive, so an unregistered path like `/tmp` stays a value.

## Generate help and load commands lazily

Generate a small Python module containing the command registry and preformatted help:

```sh
argly gen --package mycli.commands --name mycli --output mycli/generated.py
```

Then use it in `mycli/__main__.py`:

```python
from argly import App
from mycli.generated import REGISTRY, get_help

raise SystemExit(App.from_registry(REGISTRY, help_lookup=get_help).run())
```

Now you can run `python -m mycli remote add origin -u example.com`.

Generation imports your command modules to read their definitions. At runtime, only the selected command's module gets imported, and only its handler runs. Related commands in the same file share that import. Help comes straight from the generated text, without loading command modules.

Regenerate after changing command definitions. Add `--check` to the same generation command in CI to catch stale output without rewriting it. `python -m argly gen` works too.

While experimenting, you can skip generation and use `App.discover("mycli", "mycli.commands").run()`. That imports the command modules up front.

## Performance and development

Argly builds its parser tables once and reuses them. The [benchmark script](benchmarks/bench.py) compares equivalent invocations with `argparse` and measures help lookup and startup separately.

With the development dependencies installed:

```sh
python -m pytest --cov=argly --cov-branch
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build --outdir dist/release
python -m twine check --strict dist/release/*
python benchmarks/bench.py
```

The release artifacts go in `dist/release` to keep them separate from local native builds.

There's also an optional Cython build of the same parser. To build a native wheel in PowerShell, with a C compiler installed:

```powershell
python -m pip install -e ".[dev,cython]"
$env:ARGLY_CYTHON = "1"
python -m build --wheel --no-isolation
Remove-Item Env:\ARGLY_CYTHON
```

The native wheel is written to `dist`; install it to use the compiled parser. Regular builds use pure Python.
