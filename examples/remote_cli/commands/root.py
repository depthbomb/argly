from typing import Annotated
from argly import Count, group

@group('', summary='Manage named remotes.')
def root(*, verbose: Annotated[int, Count('-v', '/V', help='Increase verbosity')] = 0) -> None:
    pass
