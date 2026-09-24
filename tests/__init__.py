from argly import App
from pathlib import Path
from types import ModuleType
from argly.codegen import artifacts

def prepared(app: App, directory: Path) -> tuple[App, dict[str, ModuleType]]:
    """Load generated artifacts in memory for parser equivalence tests."""
    modules = {}
    for path, text in artifacts(app, directory / 'generated.py').items():
        if path.stem.endswith(('_runtime', '_metadata', '_help')):
            module = ModuleType(path.stem)
            exec(compile(text, str(path), 'exec'), module.__dict__)
            modules[path.stem.rsplit('_', 1)[1]] = module

    return App.from_generated(modules['runtime'], help_lookup=modules['help'].HELP.get, registry_loader=modules['metadata'].get_registry), modules
