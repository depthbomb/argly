"""Measure equivalent CLI workloads with independent, shuffled worker processes.

The README describes timing boundaries and adapter differences. JSON contains
all samples, source hashes, versions, and setup costs. No workers run in parallel.
"""
import sys
from gc import enable
from os import environ
from pathlib import Path
from timeit import Timer
from random import Random
from hashlib import sha256
from json import dumps, loads
from statistics import median
from time import perf_counter_ns
from datetime import UTC, datetime
from argparse import ArgumentParser
from platform import uname, processor
from importlib.metadata import version
from tempfile import TemporaryDirectory
from subprocess import run, PIPE, DEVNULL, check_output
from comparison_workloads import CASES, LABELS, selected, LIBRARIES, supported, write_fixtures

def _worker(library, case, directory, mode, *settings):
    return [
        sys.executable, str(Path(__file__).with_name('comparison_worker.py')),
        library, case, str(directory), mode, *map(str, settings),
    ]

def _environment():
    env = dict(environ)
    env.update(PYTHONUTF8='1', PYTHONHASHSEED='0', NO_COLOR='1', TERM='dumb', COLUMNS='80', LINES='24', SHELL_VERBOSITY='0', TYPER_USE_RICH='1')
    for key in ('FORCE_COLOR', 'CLICOLOR_FORCE', 'PYTHONDONTWRITEBYTECODE'):
        env.pop(key, None)

    return env

def _launch(command, env, *, capture=False):
    start = perf_counter_ns()
    result = run(command, env=env, stdin=DEVNULL, stdout=PIPE if capture else DEVNULL, stderr=PIPE, timeout=180)
    elapsed = (perf_counter_ns() - start) / 1e6
    if result.returncode:
        raise RuntimeError(f'{command!r}\n{result.stderr.decode("utf-8", errors="replace")}')

    return result.stdout if capture else elapsed

def _cpu():
    if sys.platform == 'win32':
        from winreg import OpenKey, QueryValueEx, HKEY_LOCAL_MACHINE

        with OpenKey(HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            return QueryValueEx(key, 'ProcessorNameString')[0].strip()

    return processor()

def _positive_int(value):
    result = int(value)
    if result < 1:
        raise ValueError('must be positive')

    return result

def _summary(samples):
    center = median(samples)

    return {
        'median': center, 'mad': median(abs(value - center) for value in samples),
        'min': min(samples), 'max': max(samples),
    }

def _prepare(directory):
    from argly.codegen import generate
    from comparison_apps import build_argly

    write_fixtures(directory)
    sys.path.insert(0, str(directory))
    setup = {}
    for case, count in CASES.items():
        start = perf_counter_ns()
        app = build_argly(case)
        build_ms = (perf_counter_ns() - start) / 1e6
        references = [item['handler'] for item in app.registry['commands'] if item['handler']]
        assert len(references) == len(set(references)) == count
        before = set(directory.glob('*.py'))
        start = perf_counter_ns()
        generate(app, directory / f'prepared_{case}.py')
        generation_ms = (perf_counter_ns() - start) / 1e6
        artifacts = set(directory.glob('*.py')) - before
        setup[case] = {
            'build_ms': build_ms, 'generation_ms': generation_ms,
            'artifact_bytes': sum(path.stat().st_size for path in artifacts),
            'handler_count': len(references),
        }

    return setup

def _table(results, group, cases, title):
    print(title)
    print('| Library | ' + ' | '.join(cases.values()) + ' |')
    print('| --- | ' + ' | '.join('---:' for _ in cases) + ' |')
    for library in results['libraries']:
        cells = []
        for case in cases:
            measurement = results[group][library].get(case)
            if measurement is None:
                cells.append('N/A')
            else:
                stats = measurement['summary']
                cells.append(f'{stats["median"]:,.1f} ± {stats["mad"]:,.1f}')

        label = LABELS[library]
        if library in results['versions'] and library != 'argly':
            label += ' ' + results['versions'][library]

        print('| ' + ' | '.join([label, *cells]) + ' |')

    print()

def measure_warm(invoke, arguments, batches, target):
    for args in arguments:
        assert invoke(args) == 0

    def cycle():
        for args in arguments:
            invoke(args)

    # Keep collection enabled: repeated real invocations also pay for garbage.
    timer = Timer(cycle, setup=enable)
    loops = 1
    while timer.timeit(loops) < target:
        loops *= 2

    timer.timeit(loops)
    samples = [timer.timeit(loops) * 1e6 / (loops * len(arguments)) for _ in range(batches)]

    return {'median_us': median(samples), 'samples_us': samples, 'loops': loops, 'calls_per_loop': len(arguments)}

def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--processes', type=_positive_int, default=9, help='independent workers per configuration')
    parser.add_argument('--batches', type=_positive_int, default=3, help='timed batches per warm worker')
    parser.add_argument('--target-ms', type=_positive_int, default=100, help='minimum calibrated warm batch duration')
    parser.add_argument('--seed', type=int, default=20260924)
    parser.add_argument('--output', type=Path, required=True, help='JSON path outside the checkout')
    parser.add_argument('--libraries', nargs='+', choices=LIBRARIES, default=list(LIBRARIES))
    args = parser.parse_args()
    env = _environment()
    rng = Random(args.seed)
    root = Path(__file__).resolve().parents[1]
    sources = [*root.glob('argly/*.py'), *root.glob('benchmarks/compar*.py'), root / 'benchmarks/requirements.txt', root / 'pyproject.toml']
    hashes = {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest() for path in sorted(sources)}
    versions = {name: version(name) for name in ('argly', 'click', 'typer', 'cleo', 'cyclopts')}
    versions['argparse'] = sys.version.split()[0]
    results = {
        'date': datetime.now(UTC).isoformat(), 'python': sys.version,
        'platform': uname()._asdict(), 'cpu': _cpu(),
        'base_commit': check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'dirty': bool(check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()),
        'source_sha256': hashes, 'versions': versions,
        'packages': loads(check_output([sys.executable, '-m', 'pip', 'list', '--format=json'], text=True)),
        'processes': args.processes, 'batches': args.batches, 'target_ms': args.target_ms,
        'seed': args.seed, 'gc_enabled': True, 'libraries': args.libraries,
        'environment': {key: env[key] for key in ('PYTHONUTF8', 'NO_COLOR', 'TERM', 'COLUMNS', 'LINES', 'SHELL_VERBOSITY', 'TYPER_USE_RICH')},
        'selected_paths': {case: [spec['path'] for spec in selected(case)] for case in CASES},
        'warm': {library: {} for library in args.libraries},
        'startup': {library: {} for library in args.libraries},
        'baseline_ms': [], 'rounds': [],
        'omissions': {'cleo/flat': 'Cleo 2.1 Application requires a command name; no private API workaround.'},
    }
    from argly import _parser

    results['parser_module'] = _parser.__file__
    with TemporaryDirectory(prefix='argly-comparison-') as temporary:
        directory = Path(temporary)
        results['preparation'] = _prepare(directory)
        pairs = [(library, case) for library in args.libraries for case in CASES if supported(library, case)]
        jobs = [(library, case, 'warm') for library, case in pairs]
        jobs += [(library, case, 'run') for library, case in pairs]
        jobs += [(library, case, 'help') for library in args.libraries for case in ('nested50', 'commands500')]
        for library, case in pairs:
            _launch(_worker(library, case, directory, 'check'), env, capture=True)

        print(f'Validated {len(pairs)} adapters, including handler identity, typed values, defaults, errors, and help.', file=sys.stderr)
        # Populate bytecode/file caches, including the generated main() route.
        for library, case, mode in jobs:
            if mode != 'warm':
                for index in range(len(selected(case))):
                    _launch(_worker(library, case, directory, mode, index), env)

        for index in range(args.processes):
            hash_seed = str(rng.getrandbits(32))
            env['PYTHONHASHSEED'] = hash_seed
            batch = [*jobs, None]
            rng.shuffle(batch)
            results['rounds'].append({'hash_seed': hash_seed, 'order': batch})
            for job in batch:
                if job is None:
                    results['baseline_ms'].append(_launch([sys.executable, '-c', 'pass'], env))
                    continue

                library, case, mode = job
                if mode == 'warm':
                    output = _launch(
                        _worker(library, case, directory, mode, args.batches, args.target_ms / 1000), env, capture=True,
                    )
                    measurement = results['warm'][library].setdefault(case, {'workers': []})
                    measurement['workers'].append(loads(output))
                else:
                    elapsed = _launch(_worker(library, case, directory, mode, index), env)
                    measurement = results['startup'][library].setdefault(f'{case}_{mode}', {'samples_ms': []})
                    measurement['samples_ms'].append(elapsed)

            print(f'Independent process round {index + 1}/{args.processes}', file=sys.stderr)

    for cases in results['warm'].values():
        for measurement in cases.values():
            measurement['summary'] = _summary([worker['median_us'] for worker in measurement['workers']])

    for cases in results['startup'].values():
        for measurement in cases.values():
            measurement['summary'] = _summary(measurement['samples_ms'])

    results['baseline'] = _summary(results['baseline_ms'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(results, indent=2) + '\n', encoding='utf-8')
    print(f'Results: {args.output}\nMedian ± median absolute deviation (MAD).\n')
    _table(results, 'warm', {'flat': 'Flat (µs)', 'commands10': '10 commands (µs)', 'nested50': 'Nested 50 (µs)'}, 'Warm invocation')
    _table(results, 'startup', {
        'flat_run': 'Flat (ms)', 'commands10_run': '10 commands (ms)',
        'nested50_run': 'Nested 50 (ms)', 'nested50_help': 'Nested 50 help (ms)',
    }, 'Fresh-process latency')
    _table(results, 'warm', {'commands500': '500 commands (µs)'}, 'Warm stress case')
    _table(results, 'startup', {'commands500_run': '500 commands (ms)', 'commands500_help': '500 help (ms)'}, 'Fresh-process stress case')

if __name__ == '__main__':
    main()
