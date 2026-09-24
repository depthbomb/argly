from sys import argv
from argparse import ArgumentParser
from collections.abc import Sequence
from argly.helpgen import main as generate_main

def main(args: Sequence[str] | None = None) -> int:
    arguments = list(argv[1:] if args is None else args)
    parser = ArgumentParser(prog='argly', description='Tools for building argly applications.')
    parser.add_argument(
        'command', choices=['gen', 'docs'], help='Generate metadata or documentation'
    )
    options = parser.parse_args(arguments[:1])

    if options.command == 'docs':
        from argly.documentation import main as docs_main

        return docs_main(arguments[1:])

    return generate_main(arguments[1:], prog='argly gen')
