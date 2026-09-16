from typing import Annotated, Optional
from argly import Flag, Option, Argument, Inherited, group, command

@group('remote', summary='Inspect and update remotes.')
def remote(
        *,
        token: Annotated[Optional[str], Option('-t', '/Token', help='Authentication token')] = None,
) -> None:
    pass

@command('remote add', summary='Show how a remote would be added.')
def add(
        name: Annotated[str, Argument(help='Remote name')],
        *,
        url: Annotated[str, Option('-u', '/URL', '/U', '/u', help='Remote URL')],
        verbose: Annotated[int, Inherited()],
        token: Annotated[Optional[str], Inherited()],
        force: Annotated[bool, Flag('-f', help='Allow replacing an existing remote')] = False,
) -> int:
    print(
            f'name={name} url={url} force={force} verbose={verbose} authenticated={token is not None}'
    )

    return 0

@command('remote list', summary='Show example remotes.')
def list_remotes(*, verbose: Annotated[int, Inherited()]) -> int:
    print(f'No remotes configured (verbosity {verbose}).')

    return 0
