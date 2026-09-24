"""Shared schemas, importable fixture source, and expected invocation results."""
CASES = {'flat': 1, 'commands10': 10, 'nested50': 50, 'commands500': 500}
LIBRARIES = ('argly', 'argly-generated', 'argparse', 'click', 'typer', 'cleo', 'cyclopts')
LABELS = {
    'argly': 'argly, no generation',
    'argly-generated': 'argly, generated',
    'argparse': 'argparse',
    'click': 'Click',
    'typer': 'Typer',
    'cleo': 'Cleo',
    'cyclopts': 'Cyclopts',
}
last_result = None

def _parameter(name, kind, default, value, *, positional=False):
    return {'name': name, 'kind': kind, 'default': default, 'value': value, 'positional': positional}

def record(path, **values) -> int:
    global last_result
    last_result = (path, values)

    return 0

def reset_result():
    global last_result
    last_result = None

def specs(case, *, indices=None):
    count = CASES[case]
    result = []
    for index in range(count) if indices is None else indices:
        path = '' if case == 'flat' else f'command{index}'
        if case == 'nested50':
            path = f'group{index // 10} {path}'

        parameters = [_parameter('name', 'str', None, 'origin', positional=True)]
        family = index * 3 // count
        if family == 0:
            parameters.extend((
                _parameter('limit', 'int', 10 + index, 123),
                _parameter('force', 'bool', False, True),
                _parameter('output', 'str', f'output-{index}', 'result'),
            ))
        elif family == 1:
            parameters.extend((
                _parameter('attempts', 'int', 1 + index, 4),
                _parameter('ratio', 'float', 0.5, 1.25),
                _parameter('label', 'str', f'label-{index}', 'sample'),
            ))
        else:
            parameters.extend((
                _parameter('format', 'choice', 'text', 'json'),
                _parameter('compact', 'bool', False, True),
                _parameter('precision', 'int', 2 + index % 8, 7),
            ))

        result.append({
            'path': path, 'handler': f'handle_{index}', 'parameters': parameters,
            'module': f'fixture_{case}', 'summary': f'Execute command {index}.',
        })

    return result

def selected(case):
    count = CASES[case]
    indices = sorted({0, count // 2, count - 1})

    return specs(case, indices=indices)

def tokens(spec, *, defaults=False, help_requested=False):
    route = spec['path'].split()
    if help_requested:
        return [*route, '--help']

    result = [*route, 'origin']
    if not defaults:
        for parameter in spec['parameters'][1:]:
            result.append('--' + parameter['name'])
            if parameter['kind'] != 'bool':
                result.append(str(parameter['value']))

    return result

def expected(spec, *, defaults=False):
    return (spec['path'], {
        item['name']: item['default'] if defaults and not item['positional'] else item['value']
        for item in spec['parameters']
    })

def supported(library, case):
    # Cleo 2.1's public Application interface requires a command name. Do not
    # patch private flags or add an extra dispatch layer only to its flat case.
    return not (library == 'cleo' and case == 'flat')

def write_fixtures(directory):
    """Write identical ordinary handler modules for every framework to import.

    This creates benchmark input source, not an optimized parser. Only argly's
    separately generated plans contain precomputed framework configuration.
    """
    for case in CASES:
        commands = specs(case)
        lines = ['from comparison_workloads import record', '']
        if any(item['kind'] == 'choice' for spec in commands for item in spec['parameters']):
            lines.insert(0, 'from typing import Literal')

        for spec in commands:
            parameters = []
            for item in spec['parameters']:
                kind = "Literal['json', 'text']" if item['kind'] == 'choice' else item['kind']
                parameter = f'{item["name"]}: {kind}'
                if not item['positional']:
                    parameter += f' = {item["default"]!r}'

                parameters.append(parameter)

            parameters.insert(1, '*')
            arguments = ', '.join(f'{item["name"]}={item["name"]}' for item in spec['parameters'])
            lines.extend((
                f'def {spec["handler"]}({", ".join(parameters)}) -> int:',
                f'    {spec["summary"]!r}',
                f'    return record({spec["path"]!r}, {arguments})', '',
            ))

        path = directory / f'fixture_{case}.py'
        source = '\n'.join(lines)
        compile(source, str(path), 'exec')
        path.write_text(source, encoding='utf-8')
