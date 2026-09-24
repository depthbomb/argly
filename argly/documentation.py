from __future__ import annotations
from typing import Any
from argly._parser import Node
from collections.abc import Mapping, Sequence
from argly.helpgen import usage, relationship, write_output, value_constraints

def _parameter(spec: Mapping[str, Any], windows: bool) -> dict[str, Any]:
    from copy import deepcopy

    fields = ('type', 'required', 'multiple', 'nullable', 'default', 'choices', 'help', 'metavar')
    result = {field: deepcopy(spec[field]) for field in fields}
    result['name'] = spec['dest']
    result['constraints'] = deepcopy(spec.get('constraints', {}))
    result['names'] = [name for name in spec.get('names', []) if windows or not name.startswith('/')]
    if 'action' in spec:
        result['action'] = spec['action']

    if result['type'] == 'path' and result['default'] is not None:
        from pathlib import Path

        default = result['default']
        result['default'] = [Path(item).as_posix() for item in default] if result['multiple'] else Path(default).as_posix()

    return result

def _describe(name: str, nodes: Mapping[str, Node], path: str | None) -> dict[str, Any]:
    from copy import deepcopy

    if path is not None and path not in nodes:
        raise ValueError(f'unknown command path {path!r}')

    commands = []
    for command_path, node in sorted(nodes.items()):
        if path is not None and command_path != path:
            continue

        commands.append({
            'path': command_path,
            'summary': node.summary,
            'usage': usage(name, node),
            'help_flags': ['--help', '-h'],
            'subcommands': [{'name': child, 'path': item.path, 'summary': item.summary} for child, item in sorted(node.children.items())],
            'options': [_parameter(spec, node.windows_options) for spec in node.options],
            'arguments': [_parameter(spec, node.windows_options) for spec in node.arguments],
            'rules': deepcopy(node.rules),
        })

    return {'schema_version': 1, 'name': name, 'commands': commands}

def _markdown(text: str) -> str:
    from html import escape

    text = escape(text, quote=False)
    for character in '\\`*_{}[]()#+-.!|':
        text = text.replace(character, '\\' + character)

    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')

def _details(spec: dict[str, Any]) -> str:
    details = [spec['help']] if spec['help'] else []
    if spec['choices'] is not None:
        details.append('Choices: ' + ', '.join(map(str, spec['choices'])))

    if spec['multiple'] or spec.get('action') == 'count':
        details.append('Repeatable.')

    if spec['nullable']:
        details.append('May be omitted with a None default.')

    details.extend(value_constraints(spec))

    return ' '.join(details)

def _markdown_document(document: dict[str, Any]) -> str:
    from re import findall

    name = document['name']
    lines = ['# ' + _markdown(name) + ' command reference', '']
    for command in document['commands']:
        title = name + (' ' + command['path'] if command['path'] else '')
        lines.extend(('## ' + _markdown(title), '', _markdown(command['summary']), ''))
        synopsis = command['usage']
        fence = '`' * max(3, 1 + max(map(len, findall(r'`+', synopsis)), default=0))
        lines.extend((fence + 'text', synopsis, fence, ''))
        if command['subcommands']:
            lines.extend(('### Subcommands', ''))
            lines.extend('- **' + _markdown(child['name']) + '**: ' + _markdown(child['summary']) for child in command['subcommands'])
            lines.append('')

        for title, specs in (('Arguments', command['arguments']), ('Options', command['options'])):
            if not specs:
                continue

            lines.extend(('### ' + title, '', '| Parameter | Type | Required | Default | Description |', '| --- | --- | --- | --- | --- |'))
            for spec in specs:
                label = ', '.join(spec['names']) if spec['names'] else spec['metavar']
                kind = 'list[' + spec['type'] + ']' if spec['multiple'] else spec['type']
                default = 'Required' if spec['required'] else repr(spec['default'])
                columns = (label, kind, 'yes' if spec['required'] else 'no', default, _details(spec))
                lines.append('| ' + ' | '.join(_markdown(column) for column in columns) + ' |')
            lines.append('')

        lines.extend(('Use --help or -h to display command help.', ''))
        if command['rules']:
            lines.extend(('### Parameter relationships', ''))
            lines.extend('- ' + _markdown(relationship(rule)) for rule in command['rules'])
            lines.append('')

    return '\n'.join(lines)

def _roff(text: str) -> str:
    text = text.replace('\\', '\\e').replace('-', '\\-').replace('"', '\\(dq')
    return '\n'.join('\\&' + line for line in text.splitlines())

def _man_document(document: dict[str, Any]) -> str:
    name = document['name']
    lines = ['.TH "' + _roff(name.upper()) + '" "1" "" "" "User Commands"', '.SH NAME', _roff(name + ' - command reference')]
    for command in document['commands']:
        title = name + (' ' + command['path'] if command['path'] else '')
        lines.extend(('.SH "' + _roff(title.upper()) + '"', _roff(command['summary']), '.SS Synopsis', '.nf', _roff(command['usage']), '.fi'))
        if command['subcommands']:
            lines.append('.SS Subcommands')
            for child in command['subcommands']:
                lines.extend(('.TP', _roff(child['name']), _roff(child['summary'])))

        for title, specs in (('Arguments', command['arguments']), ('Options', command['options'])):
            if not specs:
                continue

            lines.append('.SS ' + title)
            for spec in specs:
                label = ', '.join(spec['names']) if spec['names'] else spec['metavar']
                detail = _details(spec)
                detail += ' Type: ' + spec['type'] + '.'
                detail += ' Required.' if spec['required'] else ' Default: ' + repr(spec['default']) + '.'
                lines.extend(('.TP', _roff(label), _roff(detail)))

        lines.extend(('.TP', '\\-h, \\-\\-help', 'Show command help.'))
        if command['rules']:
            lines.append('.SS "Parameter relationships"')
            for rule in command['rules']:
                lines.extend(('.PP', _roff(relationship(rule))))

    return '\n'.join(lines) + '\n'

def render(name: str, nodes: Mapping[str, Node], output_format: str = 'markdown', *, path: str | None = None) -> str:
    """Render metadata as Markdown, a section-1 man page, or versioned JSON.

    JSON schema version 1 is described by App.export_docs. Defaults and choices
    use registry wire values: enum values, ISO dates, UUID strings, and custom
    serializer output. Consumers should ignore unknown fields for compatibility.
    """
    if output_format not in ('markdown', 'man', 'json'):
        raise ValueError(f'unsupported documentation format {output_format!r}')

    document = _describe(name, nodes, path)
    if output_format == 'markdown':
        return _markdown_document(document)

    if output_format == 'man':
        return _man_document(document)

    from json import dumps

    return dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + '\n'

def main(args: Sequence[str] | None = None) -> int:
    """Export from an importable generated registry, without discovering handlers."""
    from pathlib import Path
    from argly.app import App
    from argparse import ArgumentParser
    from sys import path as module_path
    from argly._references import resolve

    parser = ArgumentParser(prog='argly docs', description='Export command documentation from generated metadata.')
    parser.add_argument('--registry', required=True, help='Generated module or module:attribute reference')
    parser.add_argument('--format', choices=('markdown', 'man', 'json'), default='markdown')
    parser.add_argument('--command', help='Select one command path, including an empty root path')
    parser.add_argument('--output', type=Path, help='Output file; defaults to stdout')
    parser.add_argument('--check', action='store_true', help='Check that an output file is current')
    options = parser.parse_args(args)
    if options.check and options.output is None:
        parser.error('--check requires --output')

    directory = str(Path.cwd())
    added_path = directory not in module_path
    if added_path:
        module_path.insert(0, directory)

    try:
        reference = options.registry if ':' in options.registry else options.registry + ':REGISTRY'
        app = App.from_registry(resolve(reference))
        document = app.export_docs(options.format, path=options.command)
        if options.output is None:
            print(document, end='')
        elif not write_output(options.output, document.encode('utf-8'), check=options.check):
            parser.exit(1, f'{options.output} is missing or stale; regenerate it\n')
    except (ValueError, OSError, ImportError, AttributeError, TypeError, KeyError) as error:
        parser.exit(2, f'argly docs: {error}\n')
    finally:
        if added_path:
            module_path.remove(directory)

    return 0
