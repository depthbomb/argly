from argly import App
from examples.remote_cli.generated import REGISTRY, get_help

raise SystemExit(App.from_registry(REGISTRY, help_lookup=get_help).run())
