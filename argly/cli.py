from sys import argv
from typing import Optional
from argparse import ArgumentParser
from collections.abc import Sequence
from argly.helpgen import main as generate_main

def main(args: Optional[Sequence[str]] = None) -> int:
    arguments = list(argv[1:] if args is None else args)
    parser = ArgumentParser(prog='argly', description='Tools for building argly applications.')
    parser.add_argument(
            'command', choices=['gen'], help='Generate static help and a command registry'
    )
    parser.parse_args(arguments[:1])

    return generate_main(arguments[1:], prog='argly gen')
