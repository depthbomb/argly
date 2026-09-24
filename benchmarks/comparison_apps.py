"""Use each framework's normal invocation pipeline with shared handler modules."""
from importlib import import_module
from comparison_workloads import specs

class Adapter:
    def __init__(self, invoke, usage_errors=()):
        self.invoke = invoke
        self.usage_errors = usage_errors

def _handlers(case):
    module = import_module(f'fixture_{case}')

    return [(spec, getattr(module, spec['handler'])) for spec in specs(case)]

def _argparse(case):
    from argparse import ArgumentParser

    app = ArgumentParser(prog='tool')
    parents = {'': app}
    subparsers = {}
    for spec, handler in _handlers(case):
        path = spec['path']
        prefix = ''
        for part in path.split():
            route = f'{prefix} {part}'.strip()
            if route not in parents:
                if prefix not in subparsers:
                    subparsers[prefix] = parents[prefix].add_subparsers(required=True)

                parents[route] = subparsers[prefix].add_parser(part)

            prefix = route

        child = parents[path]
        child.description = spec['summary']
        for item in spec['parameters']:
            name = item['name'] if item['positional'] else '--' + item['name']
            settings = {'help': f'Value for {item["name"]}.'}
            if not item['positional']:
                settings['default'] = item['default']

            if item['kind'] == 'bool':
                settings['action'] = 'store_true'
            elif item['kind'] == 'choice':
                settings['choices'] = ('json', 'text')
            else:
                settings['type'] = {'int': int, 'float': float, 'str': str}[item['kind']]

            child.add_argument(name, **settings)

        child.set_defaults(handler=handler)

    def invoke(args):
        values = vars(app.parse_args(args))
        handler = values.pop('handler')

        return handler(**values)

    return Adapter(invoke)

def _click(case):
    from click import Group, Choice, Option, Command, Argument, UsageError

    app = None if case == 'flat' else Group('tool')
    parents = {'': app}
    for spec, handler in _handlers(case):
        prefix = ''
        parts = spec['path'].split()
        for part in parts[:-1]:
            route = f'{prefix} {part}'.strip()
            if route not in parents:
                parents[route] = Group(part)
                parents[prefix].add_command(parents[route])

            prefix = route

        parameters = []
        for item in spec['parameters']:
            if item['positional']:
                parameters.append(Argument([item['name']]))
                continue

            kind = item['kind']
            settings = {'default': item['default'], 'help': f'Value for {item["name"]}.'}
            if kind == 'bool':
                settings['is_flag'] = True
            else:
                settings['type'] = Choice(('json', 'text')) if kind == 'choice' else {'int': int, 'float': float, 'str': str}[kind]

            parameters.append(Option(['--' + item['name']], **settings))

        child = Command(parts[-1] if parts else 'tool', callback=handler, params=parameters, help=spec['summary'])
        if case == 'flat':
            app = child
        else:
            parents[prefix].add_command(child)

    return Adapter(lambda args: app.main(args, prog_name='tool', standalone_mode=False), (UsageError,))

def _typer(case):
    from typer.main import get_command
    from typer import Typer, Option, Argument
    from typing import Annotated, get_type_hints
    from typer._click.exceptions import UsageError

    app = Typer(add_completion=False)
    parents = {'': app}
    for spec, handler in _handlers(case):
        prefix = ''
        parts = spec['path'].split()
        for part in parts[:-1]:
            route = f'{prefix} {part}'.strip()
            if route not in parents:
                parents[route] = Typer(add_completion=False)
                parents[prefix].add_typer(parents[route], name=part)

            prefix = route

        hints = get_type_hints(handler)
        for item in spec['parameters']:
            name = item['name']
            kind = hints[name]
            marker = Argument if item['positional'] else Option
            hints[name] = Annotated[kind, marker(help=f'Value for {name}.')]

        handler.__annotations__ = hints
        parents[prefix].command(parts[-1] if parts else 'run', help=spec['summary'])(handler)

    # Materialize once, like every other warm adapter. Fresh-process timing
    # includes this work, as it would when calling Typer's application object.
    entry = get_command(app)

    return Adapter(lambda args: entry.main(args, prog_name='tool', standalone_mode=False), (UsageError,))

def _cleo(case):
    from cleo.application import Application
    from cleo.commands.command import Command
    from cleo.helpers import option, argument
    from cleo.io.inputs.argv_input import ArgvInput
    from cleo.exceptions import CleoError, CleoUserError

    class Leaf(Command):
        def __init__(self, spec, handler):
            self.name = spec['path']
            self.description = spec['summary']
            self.arguments = [argument('name', description='Value for name.')]
            self.options = [option(
                item['name'], flag=item['kind'] == 'bool',
                default=None if item['kind'] == 'bool' else item['default'],
                description=f'Value for {item["name"]}.',
            ) for item in spec['parameters'][1:]]
            self.parameters = spec['parameters']
            self.callback = handler
            super().__init__()

        def handle(self):
            values = {'name': self.argument('name')}
            for item in self.parameters[1:]:
                value = self.option(item['name'])
                try:
                    if item['kind'] in ('int', 'float'):
                        value = (int if item['kind'] == 'int' else float)(value)
                    elif item['kind'] == 'choice' and value not in ('json', 'text'):
                        raise ValueError('choose json or text')
                except ValueError as error:
                    raise CleoUserError(f'{item["name"]}: {error}') from error

                values[item['name']] = value

            return self.callback(**values)

    app = Application('tool')
    app.auto_exits(False)
    app.catch_exceptions(False)
    for spec, handler in _handlers(case):
        app.add(Leaf(spec, handler))

    def invoke(args):
        input_ = ArgvInput(['tool', *args])
        input_.interactive(False)

        return app.run(input_)

    return Adapter(invoke, (CleoError,))

def _cyclopts(case):
    from typing import Annotated, get_type_hints
    from cyclopts import App, Parameter, CycloptsError

    app = App(name='tool')
    parents = {'': app}
    for spec, handler in _handlers(case):
        prefix = ''
        parts = spec['path'].split()
        for part in parts[:-1]:
            route = f'{prefix} {part}'.strip()
            if route not in parents:
                parents[route] = App(name=part)
                parents[prefix].command(parents[route])

            prefix = route

        hints = get_type_hints(handler)
        for item in spec['parameters']:
            name = item['name']
            kind = hints[name]
            hints[name] = Annotated[kind, Parameter(help=f'Value for {name}.')]

        handler.__annotations__ = hints
        if case == 'flat':
            app.default(handler)
        else:
            parents[prefix].command(App(name=parts[-1], default_command=handler, help=spec['summary']))

    return Adapter(
        lambda args: app(args, exit_on_error=False, result_action='return_value'),
        (CycloptsError,),
    )

def build_argly(case):
    from typing import Annotated, get_type_hints
    from argly import App, Flag, Option, command, Argument

    functions = []
    for spec, handler in _handlers(case):
        if not hasattr(handler, '__argly__'):
            hints = get_type_hints(handler)
            for item in spec['parameters']:
                name = item['name']
                kind = hints[name]
                marker = Argument if item['positional'] else Flag if item['kind'] == 'bool' else Option
                hints[name] = Annotated[kind, marker(help=f'Value for {name}.')]

            handler.__annotations__ = hints
            command(spec['path'], summary=spec['summary'])(handler)

        functions.append(handler)

    return App('tool', functions)

def build(library, case, *, warm=False):
    if library == 'argly':
        return Adapter(build_argly(case).run)

    if library == 'argly-generated':
        module = import_module(f'prepared_{case}')
        return Adapter(module.load().run if warm else module.main)

    return {'argparse': _argparse, 'click': _click, 'typer': _typer, 'cleo': _cleo, 'cyclopts': _cyclopts}[library](case)
