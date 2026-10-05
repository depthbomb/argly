# Changelog

## [0.2.1] - 2026-10-04

### Changed

- Avoid a second registry validation when constructing an app from command declarations.
- Copy unconstrained scalar positional defaults without processing each item in Python or copying the result twice.
- Add construction and positional-default workloads to the development benchmark.

### Fixed

- Integer range bounds larger than the floating-point limit no longer raise `OverflowError` during application construction.

## [0.2.0] - 2026-09-24

### Added

- Prepared code generation through `argly gen --prepared`, including parser data, parameter bindings, conversions, and validation. Command nodes are loaded as needed.
- Generated entry points that serve straightforward `--help` requests without importing argly or command handlers.
- Support for `UUID`, `date`, `datetime`, and string- or integer-valued enums.
- Custom types through `Converter`, including serialization of defaults and choices.
- Declarative validation through `Range`, `PathRule`, `MutuallyExclusive`, `AtLeastOne`, and `Requires`.
- Async command handlers and `App.run_async()`.
- Managed resource injection through `Resource()`, with synchronous and asynchronous context managers, shared values, and cleanup after completion, errors, or cancellation.
- Structured usage errors with command context, parameter details, original input, and typo suggestions.
- `UsageError.to_dict()` and overridable `App.format_error()` for custom error reporting.
- Markdown, man-page, and JSON documentation exports through `App.export_docs()` and `argly docs`, with command selection and stale-output checks.
- Generated artifact compatibility checks, importable-reference validation, and freshness checks across all generated files.

### Changed

- List defaults are only copied when supplied arguments do not replace them.
- Registry loading validates defaults, choices, and option configurations more strictly.
- Updated the example application to use prepared generation.

### Fixed

- Factory-created commands sharing a qualified function name could dispatch to the wrong handler.
- Generated relative path defaults and choices could use platform-specific separators.
- Path-related diagnostics could report normalized values instead of the original input.
- Generated plans could include unused conversion or validation helpers.
- Source distributions now include the benchmark dependency file.
