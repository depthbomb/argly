"""Run the prepared remote CLI.

Regenerate its artifacts from the project root with:
    python -m argly gen --prepared --package examples.remote_cli.commands --name tool --windows-options --output examples/remote_cli/generated.py
"""
from examples.remote_cli.generated import main

raise SystemExit(main())
