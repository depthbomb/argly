"""Generated argly entry point. Ship its sibling modules with this file."""
from importlib import import_module as _import_module

def _module(name):
    return _import_module('.' + name, __package__) if __package__ else _import_module(name)

def get_help(path):
    return _module('_generated_189297381fba64746d83_help').HELP.get(path)

def get_registry():
    return _module('_generated_189297381fba64746d83_metadata').get_registry()

def load(*, resources=None):
    from argly import App

    return App.from_generated(_module('_generated_189297381fba64746d83_runtime'), help_lookup=get_help, registry_loader=get_registry, resources=resources)

def main(args=None, *, out=None, err=None, resources=None):
    from sys import argv, stdout

    arguments = list(argv[1:] if args is None else args)
    if arguments and arguments[-1] in ('--help', '-h'):
        tokens = arguments[:-1]
        path = ' '.join(tokens)
        if path.split() == tokens:
            text = get_help(path)
            if text is not None:
                (stdout if out is None else out).write(text)
                return 0

    return load(resources=resources).run(arguments, out=out, err=err)

if __name__ == '__main__':
    raise SystemExit(main())
