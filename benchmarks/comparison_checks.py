"""Semantic checks kept outside timing and limited to expected usage failures."""
from io import StringIO
from importlib import import_module
from contextlib import redirect_stderr, redirect_stdout
from comparison_workloads import tokens, expected, selected, reset_result

def _call(adapter, args):
    output, errors = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        try:
            status = adapter.invoke(args)
        except SystemExit as error:
            status = error.code
        except adapter.usage_errors as error:
            status = 2
            format_message = getattr(error, 'format_message', None)
            errors.write(format_message() if format_message is not None else str(error))

    return status, output.getvalue(), errors.getvalue()

def validate(adapter, case):
    workload = import_module('comparison_workloads')
    for spec in selected(case):
        for defaults in (False, True):
            reset_result()
            status, output, errors = _call(adapter, tokens(spec, defaults=defaults))
            assert status == 0 and not output and not errors, (status, output, errors)
            wanted = expected(spec, defaults=defaults)
            assert workload.last_result == wanted, (workload.last_result, wanted)
            assert {key: type(value) for key, value in workload.last_result[1].items()} == {
                key: type(value) for key, value in wanted[1].items()
            }

        route = spec['path'].split()
        first = spec['parameters'][1]
        failures = [
            ([*route, '--' + first['name'], str(first['value'])], 'name'),
            ([*route, 'origin', '--unknown-option'], 'unknown-option'),
        ]
        for item in spec['parameters'][1:]:
            if item['kind'] in ('int', 'float', 'choice'):
                failures.append(([*route, 'origin', '--' + item['name'], 'invalid'], item['name']))

        for args, parameter in failures:
            reset_result()
            status, output, errors = _call(adapter, args)
            assert status not in (0, None) and workload.last_result is None, args
            assert parameter in (output + errors).lower(), (args, output, errors)

        reset_result()
        status, output, errors = _call(adapter, tokens(spec, help_requested=True))
        assert status in (0, None) and workload.last_result is None and not errors
        for item in spec['parameters']:
            name = item['name'] if item['positional'] else '--' + item['name']
            assert name in output.lower(), output
