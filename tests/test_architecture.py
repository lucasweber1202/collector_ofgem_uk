"""Regression gate for the standalone-repository contract."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_code_has_no_cross_repository_dependencies() -> None:
    forbidden_paths = ("../collector_", "..\\\\collector_", "sys.path", "PYTHONPATH")
    for path in [ROOT / "main.py", *(ROOT / "scripts").glob("*.py")]:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden_paths), path
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("collector_") for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("collector_"), path


def test_schema_name_is_repository_name() -> None:
    from scripts.config import SCHEMA_NAME

    assert SCHEMA_NAME == ROOT.name
