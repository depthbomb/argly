from __future__ import annotations
from pathlib import Path
from argly.app import App
from pprint import pformat
from os import chmod, replace
from argly._parser import Node
from argparse import ArgumentParser
from sys import path as module_path
from tempfile import NamedTemporaryFile
from collections.abc import Mapping, Sequence

def _rows(items: list[tuple[str, str]]) -> list[str]:
    width = min(max((len(label) for label, _ in items), default=0), 36)
    rows = []
    for label, description in items:
        if len(label) > width:
            rows.append(f'  {label}\n{" " * (width + 4)}{description}')
        else:
            rows.append(f'  {label:<{width}}  {description}'.rstrip())

    return rows

def usage(name: str, node: Node) -> str:
    """Describe an invocation consistently across help and exported documentation."""
    invocation = name + (' ' + node.path if node.path else '')
    synopsis = f'Usage: {invocation} [options]'
    if node.children:
        synopsis += ' <command>' if node.handler is None else ' [command]'

    for argument in node.arguments:
        label = argument['metavar'] + ('...' if argument['multiple'] else '')
        synopsis += ' ' + (f'<{label}>' if argument['required'] else f'[{label}]')

    return synopsis

def value_constraints(spec: Mapping[str, object]) -> list[str]:
    """Human-readable constraints without running validators or converters."""
    rules = spec.get('constraints')
    if not isinstance(rules, dict):
        return []

    details = []
    if rules.get('minimum') is not None:
        details.append(f'minimum: {rules["minimum"]}')

    if rules.get('maximum') is not None:
        details.append(f'maximum: {rules["maximum"]}')

    path = rules.get('path')
    if isinstance(path, dict):
        if path.get('exists') is not None:
            details.append('must exist' if path['exists'] else 'must not exist')

        if path.get('kind') is not None:
            details.append('must be a ' + path['kind'])

        for access in ('readable', 'writable'):
            if path.get(access):
                details.append('must be ' + access)

    return details

def relationship(rule: Mapping[str, object]) -> str:
    """Explain a rule over explicitly supplied parameters."""
    parameters = rule['parameters']
    assert isinstance(parameters, list)
    if rule['kind'] == 'exclusive':
        return 'Supply at most one of: ' + ', '.join(parameters)

    if rule['kind'] == 'requires':
        return f'{parameters[0]} requires: ' + ', '.join(parameters[1:])

    return 'Supply at least one of: ' + ', '.join(parameters)

def render(name: str, node: Node) -> str:
    """Render one help page from compiled metadata without importing handlers."""
    lines = [usage(name, node)]
    if node.summary:
        lines.extend(('', node.summary))

    if node.children:
        lines.extend(('', 'Commands:'))
        lines.extend(
            _rows(
                [
                    (name, child.summary.splitlines()[0] if child.summary else '')
                    for name, child in sorted(node.children.items())
                ]
            )
        )

    if node.arguments:
        lines.extend(('', 'Arguments:'))
        lines.extend(_rows([(item['metavar'], ' '.join([item['help'], *value_constraints(item)]).strip()) for item in node.arguments]))

    lines.extend(('', 'Options:'))
    rows = [('-h, --help', 'Show this help and exit')]
    inherited_names: set[str] = set()
    for child in node.children.values():
        inherited_names.update(option['dest'] for option in child.options)

    for option in node.options:
        names = [
            name for name in option['names'] if node.windows_options or not name.startswith('/')
        ]
        label = ', '.join(names)
        if option['action'] == 'value':
            label += ' ' + option['metavar']

        details = [option['help']] if option['help'] else []
        if option['required']:
            details.append('(required)')
        elif option['default'] is not None:
            details.append(f'[default: {option["default"]}]')

        if option['choices'] is not None:
            details.append('[choices: ' + ', '.join(map(str, option['choices'])) + ']')

        if option['multiple'] or option['action'] == 'count':
            details.append('(repeatable)')

        details.extend('[' + constraint + ']' for constraint in value_constraints(option))

        if option['dest'] in inherited_names:
            details.append('(also applies to subcommands)')

        rows.append((label, ' '.join(details)))

    lines.extend(_rows(rows))
    if node.rules:
        lines.extend(('', 'Constraints:'))
        lines.extend('  ' + relationship(rule) for rule in node.rules)

    return '\n'.join(lines) + '\n'

def source(app: App, *, help_only: bool = False) -> str:
    """Generate an import-free module with static help and optional registry data."""
    if not help_only:
        from argly.codegen import validate_references

        validate_references(app.registry)

    app = App.from_registry(app.registry)

    lines = ['# Generated by argly gen. Regenerate after changing command definitions.', '']
    if not help_only:
        ordered_resources = any(entry.get('resources') for entry in app.registry['commands'])
        lines.extend(('REGISTRY = ' + pformat(app.registry, width=100, sort_dicts=not ordered_resources), ''))

    lines.append('HELP = {')
    # Generate help from the compiled tree, without using a possibly stale help lookup.
    # noinspection PyProtectedMember
    for path, node in sorted(app._nodes.items()):
        lines.append(f'    {path!r}: {render(app.name, node)!r},')

    lines.extend(('}', '', '', 'def get_help(path):', '    return HELP.get(path)', ''))

    return '\n'.join(lines)

def generate(app: App, output: Path, *, check: bool = False, help_only: bool = False) -> bool:
    """Write atomically, or check freshness. Return False for stale check output."""
    if output.suffix != '.py':
        raise ValueError('help output must be a .py file')

    data = source(app, help_only=help_only).encode('utf-8')
    compile(data, output.name, 'exec')

    return write_output(output, data, check=check)

def write_output(output: Path, data: bytes, *, check: bool = False) -> bool:
    """Share atomic, permission-preserving writes between generated artifacts."""
    try:
        existing = output.read_bytes()
    except FileNotFoundError:
        existing = None

    if existing == data:
        return True

    if check:
        return False

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=output.parent, prefix='.argly-', suffix='.tmp', delete=False
        ) as stream:
            written_path = Path(stream.name)
            temporary = written_path
            stream.write(data)

        if output.exists():
            chmod(written_path, output.stat().st_mode)

        replace(written_path, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return True

def main(args: Sequence[str] | None = None, *, prog: str | None = None) -> int:
    """Discover command definitions and generate a standalone Python module."""
    parser = ArgumentParser(
        prog=prog, description='Generate static argly help and a lazy command registry.'
    )
    parser.add_argument(
        '--package', required=True, help='Importable package containing command modules'
    )
    parser.add_argument('--name', required=True, help='Application name displayed in help')
    parser.add_argument('--output', type=Path, required=True, help='Generated .py module')
    parser.add_argument(
        '--windows-options', action='store_true', help='Enable explicit slash aliases'
    )
    parser.add_argument('--help-only', action='store_true', help='Omit command registry metadata')
    parser.add_argument('--prepared', action='store_true', help='Generate prepared runtime, help, and metadata modules')
    parser.add_argument('--check', action='store_true', help='Check freshness without writing')
    options = parser.parse_args(args)
    if options.help_only and options.prepared:
        parser.error('--help-only and --prepared cannot be combined')
    directory = str(Path.cwd())
    added_path = directory not in module_path
    if added_path:
        module_path.insert(0, directory)

    try:
        app = App.discover(options.name, options.package, windows_options=options.windows_options)
        if options.prepared:
            from argly.codegen import generate as generate_prepared

            current = generate_prepared(app, options.output, check=options.check)
        else:
            current = generate(app, options.output, check=options.check, help_only=options.help_only)
    except (ValueError, OSError, ImportError, TypeError, NameError) as error:
        parser.exit(2, f'argly gen: {error}\n')
    finally:
        if added_path:
            module_path.remove(directory)

    if not current:
        parser.exit(1, f'argly gen: {options.output} is missing or stale; regenerate it\n')

    return 0

if __name__ == '__main__':
    raise SystemExit(main())
