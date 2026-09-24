"""Minimal entry point; startup workers never import the measurement harness."""
import sys
from comparison_apps import build
from comparison_workloads import tokens, selected

def main():
    library, case, generated, mode, *settings = sys.argv[1:]
    sys.path.insert(0, generated)
    adapter = build(library, case, warm=mode in ('warm', 'check'))
    candidates = selected(case)
    if mode == 'check':
        from comparison_checks import validate

        validate(adapter, case)
        if library == 'argly-generated':
            validate(build(library, case), case)

    elif mode == 'warm':
        from json import dumps
        from compare import measure_warm

        arguments = [tokens(spec) for spec in candidates]
        print(dumps(measure_warm(adapter.invoke, arguments, int(settings[0]), float(settings[1]))))
    else:
        # Select beginning, middle, and end equally across process repetitions.
        spec = candidates[int(settings[0]) % len(candidates)]
        status = adapter.invoke(tokens(spec, help_requested=mode == 'help'))
        if status not in (0, None):
            raise SystemExit(status)

if __name__ == '__main__':
    main()
