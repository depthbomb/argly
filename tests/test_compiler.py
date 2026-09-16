import pytest
from copy import deepcopy
from typing import Annotated, Optional
from argly import App, Flag, Count, Option, Argument, Inherited, command, group

def test_inherited_requires_matching_ancestor_type():
    @group('')
    def root(*, verbose: Annotated[int, Count('-v')] = 0) -> None:
        pass

    @command('child')
    def child(*, verbose: Annotated[str, Inherited()]) -> int:
        return 0

    with pytest.raises(ValueError, match='different type'):
        App('tool', [root, child])

def test_inherited_cannot_have_a_second_default():
    @command('child')
    def child(*, verbose: Annotated[int, Inherited()] = 1) -> int:
        return verbose

    with pytest.raises(ValueError, match='default from the ancestor'):
        App('tool', [child])

def test_inherited_requires_existing_ancestor():
    @command('child')
    def child(*, verbose: Annotated[int, Inherited()]) -> int:
        return verbose

    with pytest.raises(ValueError, match='no ancestor'):
        App('tool', [child])

@pytest.mark.parametrize(
        'name', ['-h', '--help', '-ab', '/', '--', 'no-prefix', '--x=y', '--has space']
)
def test_invalid_or_reserved_option_names(name):
    @command('')
    def run(*, value: Annotated[str, Option(name)]) -> int:
        return 0

    with pytest.raises(ValueError, match='option'):
        App('tool', [run])

def test_options_cannot_shadow_ancestor_names_or_aliases():
    @group('')
    def root(*, value: Annotated[str, Option('-x')] = 'default') -> None:
        pass

    @command('child')
    def child(*, value: Annotated[str, Option()] = 'local') -> int:
        return 0

    with pytest.raises(ValueError, match='shadows'):
        App('tool', [root, child])

    @command('child')
    def aliases(*, another: Annotated[str, Option('-x')] = 'local') -> int:
        return 0

    with pytest.raises(ValueError, match='duplicate'):
        App('tool', [root, aliases])

def test_siblings_can_reuse_names_and_aliases():
    @command('a')
    def first(*, value: Annotated[str, Option('-v')] = 'a') -> int:
        return 0

    @command('b')
    def second(*, value: Annotated[int, Option('-v')] = 2) -> int:
        return 0

    app = App('tool', [first, second])
    assert app.parse(['a', '-vx']).kwargs == {'value': 'x'}
    assert app.parse(['b', '-v3']).kwargs == {'value': 3}

def test_implicit_ancestors_and_deep_inheritance():
    @group('')
    def root(*, verbose: Annotated[int, Count('-v')] = 2) -> None:
        pass

    @command('one two three four')
    def deep(*, verbose: Annotated[int, Inherited()]) -> int:
        return verbose

    app = App('tool', [deep, root])
    assert app.run(['one', '-v', 'two', 'three', 'four', '-v']) == 4

def test_reject_parent_positionals():
    @command('parent')
    def parent(value: Annotated[str, Argument()]) -> int:
        return 0

    @command('parent child')
    def child() -> int:
        return 0

    with pytest.raises(ValueError, match='children cannot declare positional'):
        App('tool', [parent, child])

def test_reject_duplicate_commands():
    @command('same')
    def first() -> int:
        return 0

    @command('same')
    def second() -> int:
        return 0

    with pytest.raises(ValueError, match='duplicate command'):
        App('tool', [first, second])

def test_annotated_metadata_ignores_unrelated_markers():
    @command('')
    def run(*, value: Annotated[str, 'other library', Option()] = 'x') -> int:
        return 0

    assert App('tool', [run]).parse([]).kwargs == {'value': 'x'}

@pytest.mark.parametrize(
        'annotation, default',
        [
            (Annotated[str, Flag()], 'x'),
            (Annotated[bool, Count()], False),
            (Annotated[bool, Option()], False),
            (Annotated[int, Option()], 'bad'),
            (Annotated[Optional[int], Flag()], None),
            (Annotated[int | str, Option()], 1),
            (Annotated[dict[str, int], Option()], {}),
            (int, 1),
            (Annotated[int, Option(), Option()], 1),
        ],
)
def test_invalid_declarations(annotation, default):
    @command('')
    def run(value=default) -> int:
        return 0

    run.__annotations__['value'] = annotation
    with pytest.raises(ValueError):
        App('tool', [run])

def test_only_integer_return_annotations_are_accepted():
    @command('')
    def run() -> None:
        pass

    with pytest.raises(ValueError, match='declare -> int'):
        App('tool', [run])

def test_async_handlers_are_rejected():
    @command('')
    async def run() -> int:
        return 0

    with pytest.raises(ValueError, match='synchronous'):
        App('tool', [run])

def test_registry_is_detached_and_versioned():
    @command('')
    def run(*, value: Annotated[str, Option()] = 'x') -> int:
        return 0

    original = App('tool', [run]).registry
    app = App.from_registry(original)
    original['commands'][0]['options'][0]['default'] = 'changed'
    assert app.parse([]).kwargs['value'] == 'x'
    invalid = deepcopy(original)
    invalid['version'] = 99
    with pytest.raises(ValueError, match='version'):
        App.from_registry(invalid)

def test_choices_are_rejected_for_counters():
    @command('')
    def run(*, verbose: Annotated[int, Count(choices=[0, 1])] = 0) -> int:
        return verbose

    with pytest.raises(ValueError, match='choices apply to value options'):
        App('tool', [run])

def test_nullable_inherited_types_must_match():
    @group('')
    def root(*, token: Annotated[Optional[str], Option()] = None) -> None:
        pass

    @command('child')
    def child(*, token: Annotated[str, Inherited()]) -> int:
        return 0

    with pytest.raises(ValueError, match='different type'):
        App('tool', [root, child])
