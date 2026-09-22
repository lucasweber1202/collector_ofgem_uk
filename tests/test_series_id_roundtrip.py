"""series_id round-trip over every identifier this collector can actually emit.

GUIDELINES.md 4 requires series_id to be uppercase, underscore-separated,
ordered coarse -> fine and round-trippable. Some collectors keep their ids as
literals; others assemble them from controlled vocabularies at parse time. This
harvests both -- literals found in the source, and the combinations the
repository's own vocabularies can produce -- keeps the ones this collector's
parser accepts, and asserts the property on all of them. It refuses to pass
vacuously if it finds none.
"""

from __future__ import annotations

import importlib
import itertools
import pathlib
import re
from typing import Any

import pytest

from scripts.extract import build_series_id, parse_series_id

_VOCAB = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_PREFIX = re.compile(r'f"([A-Z][A-Z0-9_]*_)\{')
_NUMERIC = re.compile(r"[A-Z]{1,3}\d{2,8}")
_CANDIDATE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,}")
_MAX_PRODUCT = 50_000
_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _parses(value: str) -> bool:
    # A series_id is structured: at least two components. A bare token is a
    # constant that happens to be uppercase, not an identifier.
    if not _CANDIDATE.fullmatch(value):
        return False
    try:
        parse_series_id(value)
    except Exception:  # noqa: BLE001 - probing, any rejection just means "not an id"
        return False
    return True


def _modules() -> list[Any]:
    loaded: list[Any] = []
    for path in sorted((_ROOT / "scripts").glob("*.py")):
        if path.stem == "__init__":
            continue
        try:
            loaded.append(importlib.import_module(f"scripts.{path.stem}"))
        except Exception as exc:  # noqa: BLE001 - probing; a helper that needs
            # runtime config is simply not a source of series ids here.
            print(f"skipping scripts.{path.stem}: {exc}")
            continue
    return loaded


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [k for k in value if isinstance(k, str)] + [
            v for v in value.values() if isinstance(v, str)
        ]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [v for v in value if isinstance(v, str)]
    return []


def _harvested() -> list[str]:
    found: set[str] = set()
    modules = _modules()

    # 1. ids that appear verbatim -- in the source, in a constant, or in this
    #    repository's own fixtures, which is where ids carrying a numeric
    #    component (a base period, a settlement period) are written down
    for path in sorted([*(_ROOT / "scripts").glob("*.py"), *(_ROOT / "tests").glob("*.py")]):
        for match in _CANDIDATE.finditer(path.read_text(encoding="utf-8")):
            if _parses(match.group(0)):
                found.add(match.group(0))
    for module in modules:
        for value in vars(module).values():
            for candidate in _strings(value):
                if _parses(candidate):
                    found.add(candidate)

    # 2. ids this collector assembles from a literal prefix plus its own
    #    controlled vocabularies, e.g. f"DESNZ_ROADFUEL_{product}_{measure}"
    prefixes: set[str] = set()
    for path in sorted((_ROOT / "scripts").glob("*.py")):
        for match in _PREFIX.finditer(path.read_text(encoding="utf-8")):
            prefixes.add(match.group(1).rstrip("_"))
    vocabularies: list[list[str]] = []
    for module in modules:
        for name, value in vars(module).items():
            if name.startswith("_"):
                continue
            tokens = sorted({s for s in _strings(value) if _VOCAB.match(s)})
            if 1 <= len(tokens) <= 80:
                vocabularies.append(tokens)
    # Components that are a code plus digits -- a base period (B200503), a
    # settlement period (SP01) -- are written as literals rather than kept in a
    # vocabulary, so mine them from the source too.
    numeric: set[str] = set()
    for path in sorted([*(_ROOT / "scripts").glob("*.py"), *(_ROOT / "tests").glob("*.py")]):
        for match in _NUMERIC.finditer(path.read_text(encoding="utf-8")):
            numeric.add(match.group(0))
    if numeric:
        vocabularies.append(sorted(numeric))
    for prefix in sorted(prefixes):
        for size in (1, 2, 3):
            for combo in itertools.combinations(vocabularies, size):
                total = 1
                for vocabulary in combo:
                    total *= len(vocabulary)
                if total > _MAX_PRODUCT:
                    continue
                for parts in itertools.product(*combo):
                    candidate = "_".join((prefix, *parts))
                    if _parses(candidate):
                        found.add(candidate)
    return sorted(found)


HARVESTED = _harvested()


def test_the_catalog_is_not_empty() -> None:
    """Guard against this file silently testing nothing."""
    assert HARVESTED, "no parseable series_id found; the round-trip test would be vacuous"


@pytest.mark.parametrize("series_id", HARVESTED)
def test_series_id_round_trips(series_id: str) -> None:
    assert build_series_id(*parse_series_id(series_id)) == series_id


@pytest.mark.parametrize("series_id", HARVESTED)
def test_series_id_is_uppercase_and_structured(series_id: str) -> None:
    assert series_id == series_id.upper()
    components = parse_series_id(series_id)
    assert len(components) >= 2, "series_id must be structured, coarse -> fine"
    assert all(components), "no empty component"


def test_lowercase_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_series_id(HARVESTED[0].lower())


def test_build_rejects_invalid_components() -> None:
    with pytest.raises(ValueError):
        build_series_id()
    with pytest.raises(ValueError):
        build_series_id("GOOD", "bad")
