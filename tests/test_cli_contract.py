"""Entrypoint contract: `python main.py` is the only supported way to run this.

A regression shipped a `return parser.parse_args(argv)` above a later
``add_argument``, so ``--start-date`` was declared but never reached the
namespace and the pipeline raised ``AttributeError`` at runtime while the unit
suite stayed green. The reachability guard below is therefore structural
rather than a list of known flags: any argument declared after the parser has
already returned fails the build, whichever flag it is.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

import main

ROOT = Path(__file__).resolve().parent.parent


def _parse_args_node() -> ast.FunctionDef:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_args":
            return node
    raise AssertionError("main.py declares no _parse_args()")


def _flags_declared_in(node: ast.AST) -> list[str]:
    """Collect the literal flag names passed to add_argument() below `node`."""
    return [
        call.args[0].value
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_argument"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ]


def _declared_flags() -> list[str]:
    return _flags_declared_in(_parse_args_node())


# -- structural guard -----------------------------------------------------


def test_no_argument_is_declared_after_the_parser_returns() -> None:
    """Every add_argument() must run before parse_args(), on every path."""
    unreachable: list[str] = []
    terminated = False
    for statement in _parse_args_node().body:
        if terminated:
            unreachable.extend(_flags_declared_in(statement))
        if isinstance(statement, ast.Return | ast.Raise):
            terminated = True
    assert unreachable == [], f"declared after _parse_args() returns: {unreachable}"


@pytest.mark.parametrize("flag", _declared_flags())
def test_every_declared_flag_reaches_the_namespace(flag: str) -> None:
    """A declared flag that argparse never saw is invisible to hasattr()."""
    dest = flag.lstrip("-").replace("-", "_")
    assert hasattr(main._parse_args([]), dest), f"{flag} never reached the namespace"


# -- the incremental contract (GUIDELINES.md 5) ---------------------------


def test_cli_default_namespace_has_start_date() -> None:
    args = main._parse_args([])
    assert hasattr(args, "start_date")
    assert args.start_date is None


def test_cli_accepts_explicit_start_date() -> None:
    args = main._parse_args(["--start-date", "2025-01-01"])
    assert args.start_date == date(2025, 1, 1)


def test_cli_rejects_a_malformed_start_date() -> None:
    with pytest.raises(SystemExit):
        main._parse_args(["--start-date", "01/01/2025"])


def test_cli_log_level_round_trips() -> None:
    assert main._parse_args([]).log_level
    assert main._parse_args(["--log-level", "DEBUG"]).log_level == "DEBUG"


# -- the real entrypoint --------------------------------------------------


def _run_entrypoint(*argv: str) -> subprocess.CompletedProcess[str]:
    """Invoke `python main.py` the way an operator does, with no database.

    COLLECTOR_DB_URL is exported empty rather than unset so the repo-root .env
    loader -- which only fills keys absent from the environment -- cannot
    reintroduce a real connection string on a developer machine.
    """
    env = dict(os.environ, COLLECTOR_DB_URL="", PROD="false", PYTHONNOUSERSITE="1")
    return subprocess.run(
        [sys.executable, "main.py", *argv],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_help_exits_cleanly_and_documents_start_date() -> None:
    result = _run_entrypoint("--help")
    assert result.returncode == 0, result.stderr
    assert "--start-date" in result.stdout


def test_entrypoint_stops_at_the_environment_gate_not_a_coding_error() -> None:
    """Without a database the run must fail at its own gate, and only there.

    AttributeError/TypeError/NameError here would mean the pipeline broke on
    its own structure before it ever reached the credential check.
    """
    result = _run_entrypoint()
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "COLLECTOR_DB_URL" in output, output
    for coding_error in ("AttributeError", "NameError", "TypeError", "SyntaxError"):
        assert coding_error not in output, f"{coding_error} in entrypoint output:\n{output}"
