import sys
import json
from pathlib import Path
from timeit import repeat
from argly import Invocation
from statistics import median
from argparse import ArgumentParser
from subprocess import check_output
from typing import Annotated, Optional
from importlib.util import module_from_spec, spec_from_file_location
from argly import App, Flag, Count, Option, Argument, Inherited, command, group

def _flat():
    @command('')
    def flat(
            name: Annotated[str, Argument()],
            *,
            verbose: Annotated[int, Count('-v')] = 0,
            force: Annotated[bool, Flag('-f')] = False,
            limit: Annotated[int, Option('-l')] = 10,
            output: Annotated[Optional[str], Option('-o')] = None,
    ) -> int:
        return 0

    app = App('tool', [flat])
    parser = ArgumentParser(prog='tool')
    parser.add_argument('name')
    parser.add_argument('--verbose', '-v', action='count', default=0)
    parser.add_argument('--force', '-f', action='store_true')
    parser.add_argument('--limit', '-l', type=int, default=10)
    parser.add_argument('--output', '-o')
    tokens = ['origin', '-vvvf', '--limit=123', '-o', 'result']
    assert app.parse(tokens).kwargs == vars(parser.parse_args(tokens))

    return app, parser, tokens

def _nested():
    @group('')
    def root(*, verbose: Annotated[int, Count('-v')] = 0) -> None:
        pass

    @command('remote add')
    def add(
            name: Annotated[str, Argument()],
            *,
            url: Annotated[str, Option('-u')],
            verbose: Annotated[int, Inherited()],
    ) -> int:
        return verbose

    app = App('tool', [root, add])
    parser = ArgumentParser(prog='tool')
    parser.add_argument('--verbose', '-v', action='count', default=0)
    remote = parser.add_subparsers(required=True).add_parser('remote')
    add_parser = remote.add_subparsers(required=True).add_parser('add')
    add_parser.add_argument('name')
    add_parser.add_argument('--url', '-u', required=True)
    tokens = ['-vv', 'remote', 'add', 'origin', '--url=https://example.com']
    assert app.parse(tokens).kwargs == vars(parser.parse_args(tokens))

    return app, parser, tokens

def _wide():
    @command('command0')
    def child(*, number: Annotated[int, Option('-n')] = 0) -> int:
        return number

    registry = App('tool', [child]).registry
    template = registry['commands'].pop()
    parser = ArgumentParser(prog='tool')
    children = parser.add_subparsers(required=True)
    for index in range(500):
        name = f'command{index}'
        registry['commands'].append({**template, 'path': name})
        children.add_parser(name).add_argument('--number', '-n', type=int, default=0)

    app = App.from_registry(registry)
    tokens = ['command499', '-n123']
    assert app.parse(tokens).kwargs == vars(parser.parse_args(tokens))

    return app, parser, tokens

def _startup(script, rounds):
    measured = 'from time import perf_counter_ns; start=perf_counter_ns(); ' + script
    measured += '; print((perf_counter_ns()-start)/1e6)'
    samples = [
        float(check_output([sys.executable, '-c', measured], text=True)) for _ in range(rounds)
    ]

    return {'median_ms': median(samples), 'samples_ms': samples}

def _compare_backends(loops, rounds):
    native = sys.modules['argly._parser']
    location = Path(native.__file__)
    if location.suffix == '.py':
        return None

    spec = spec_from_file_location('argly._parser_python', location.with_name('_parser.py'))
    pure = module_from_spec(spec)
    spec.loader.exec_module(pure)
    results = {}
    for name, factory in (('flat', _flat), ('nested', _nested), ('500_commands', _wide)):
        app, _, tokens = factory()

        def native_call(app=app, tokens=tokens):
            return Invocation(native.parse(app._root, list(tokens)))

        def python_call(app=app, tokens=tokens):
            return Invocation(pure.parse(app._root, list(tokens)))

        assert native_call().kwargs == python_call().kwargs
        for _ in range(1000):
            native_call()
            python_call()

        samples = {'native': [], 'python': []}
        for round_number in range(rounds):
            calls = [('native', native_call), ('python', python_call)]
            if round_number % 2:
                calls.reverse()

            for backend, call in calls:
                samples[backend].append(repeat(call, number=loops, repeat=1)[0])

        native_time, python_time = median(samples['native']), median(samples['python'])
        results[name] = {
            'native_us': native_time * 1e6 / loops,
            'python_us': python_time * 1e6 / loops,
            'reduction_percent': 100 * (1 - native_time / python_time),
            'samples_s': samples,
        }

    return results

def main():
    parser = ArgumentParser(
            description='Compare equivalent warm parses and measure fresh-process startup.'
    )
    parser.add_argument('--loops', type=int, default=10000)
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    results = {'python': sys.version, 'loops': args.loops, 'rounds': args.rounds, 'cases': {}}
    for name, factory in (('flat', _flat), ('nested', _nested), ('500_commands', _wide)):
        app, reference, tokens = factory()
        for _ in range(1000):
            app.parse(tokens)
            reference.parse_args(tokens)

        argly = repeat(
                lambda app=app, tokens=tokens: app.parse(tokens), number=args.loops, repeat=args.rounds
        )
        argparse = repeat(
                lambda reference=reference, tokens=tokens: reference.parse_args(tokens),
                number=args.loops,
                repeat=args.rounds,
        )
        results['cases'][name] = {
            'argly_us': median(argly) * 1e6 / args.loops,
            'argparse_us': median(argparse) * 1e6 / args.loops,
            'argly_samples_s': argly,
            'argparse_samples_s': argparse,
            'reduction_percent': 100 * (1 - median(argly) / median(argparse)),
        }

    app, _, _ = _flat()
    from argly.helpgen import source

    namespace = {}
    exec(source(app, help_only=True), namespace)
    lookup = namespace['get_help']
    dynamic = repeat(lambda: app.format_help(), number=args.loops, repeat=args.rounds)
    generated = repeat(lambda: lookup(''), number=args.loops, repeat=args.rounds)
    results['help'] = {
        'dynamic_us': median(dynamic) * 1e6 / args.loops,
        'generated_lookup_us': median(generated) * 1e6 / args.loops,
    }
    results['startup'] = {
        'import_argly': _startup('import argly', args.rounds),
        'import_argparse': _startup('import argparse', args.rounds),
        'generated_app': _startup(
                'from argly import App; from examples.remote_cli.generated import REGISTRY, get_help; '
                'app=App.from_registry(REGISTRY, help_lookup=get_help)',
                args.rounds,
        ),
        'discovered_app': _startup(
                "from argly import App; app=App.discover('tool', 'examples.remote_cli.commands', windows_options=True)",
                args.rounds,
        ),
    }
    results['parser_module'] = sys.modules['argly._parser'].__file__
    results['paired_backends'] = _compare_backends(args.loops, args.rounds)
    output = json.dumps(results, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + '\n', encoding='utf-8')

    print(output)

if __name__ == '__main__':
    main()
