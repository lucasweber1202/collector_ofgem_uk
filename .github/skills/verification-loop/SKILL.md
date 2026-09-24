---
name: verification-loop
description: Use before creating a PR or after completing a major milestone. Runs a structured sequence of quality gates to catch issues before they reach review.
---

# Verification Loop

A structured sequence of quality gates to run before merging or marking work complete. Each gate must pass before proceeding to the next.

## When to Use

- Before creating a pull request
- After completing a major feature or milestone
- After significant refactoring
- Before deploying to any shared environment

## Gate Sequence

Run gates in order. Fix failures before advancing.

```
Gate 1: Build/Import  →  Gate 2: Type Check  →  Gate 3: Lint  →  Gate 4: Tests  →  Gate 5: Security  →  Gate 6: Diff Review
```

### Gate 1: Build / Import Check

Verify the code loads without errors.

```bash
# Python: verify all modified modules import cleanly
python -c "import module_name"

# For packages with entry points
python -m package_name --help
```

**Pass criteria:** No `ImportError`, `SyntaxError`, or `ModuleNotFoundError`.

### Gate 2: Type Check

```bash
# If mypy is configured
mypy path/to/changed/files

# If pyright/pylance is available
pyright path/to/changed/files
```

**Pass criteria:** No new type errors introduced. Pre-existing errors documented if not addressed.

### Gate 3: Lint

```bash
# Preferred: ruff (fast, comprehensive)
ruff check path/to/changed/files

# Alternative: flake8
flake8 path/to/changed/files

# Auto-format check
ruff format --check path/to/changed/files
```

**Pass criteria:** No lint errors. Warnings reviewed and justified if not fixed.

### Gate 4: Tests

```bash
# Run tests related to changed code
pytest tests/ -x --tb=short

# With coverage on changed files
pytest tests/ --cov=path/to/module --cov-report=term-missing

# Run only tests affected by changes (if configured)
pytest tests/ -x --last-failed
```

**Pass criteria:**
- All tests pass
- New code has test coverage
- No existing tests broken
- Coverage on new code ≥ 80%

### Gate 5: Security Scan

```bash
# Check for known vulnerabilities in dependencies
pip-audit

# Alternative
safety check

# Check for secrets in code
grep -rn "password\|secret\|api_key\|token" --include="*.py" path/to/changed/files
```

**Pass criteria:** No known CVEs in dependencies. No hardcoded secrets. If the `security-review` skill applies, use it for deeper analysis.

### Gate 6: Diff Review

Review the actual changes that will be merged.

```bash
# Review staged changes
git diff --stat
git diff

# Review commit history
git log --oneline main..HEAD
```

**Review for:**
- [ ] No unintended file changes
- [ ] No debug artifacts (`print()`, `breakpoint()`, commented-out code)
- [ ] No temporary workarounds without TODO tracking
- [ ] Commit messages are clear and descriptive
- [ ] No large binary files or data accidentally committed

**Pass criteria:** All changes are intentional and clean.

## Verification Summary Format

After running all gates, produce a summary:

```markdown
## Verification Summary

| Gate | Status | Notes |
|------|--------|-------|
| 1. Build/Import | ✅ Pass | All modules import cleanly |
| 2. Type Check | ⚠️ Skip | mypy not configured for this module |
| 3. Lint | ✅ Pass | 0 errors, 0 warnings |
| 4. Tests | ✅ Pass | 47/47 pass, 92% coverage on new code |
| 5. Security | ✅ Pass | No CVEs, no hardcoded secrets |
| 6. Diff Review | ✅ Pass | 3 files changed, all intentional |

**Result:** ✅ Ready for PR
```

## Handling Failures

| Situation | Action |
|-----------|--------|
| Gate fails with clear fix | Fix immediately, re-run from that gate |
| Gate fails with unclear cause | Use `systematic-debugging` skill to investigate |
| Pre-existing failure unrelated to changes | Document in summary, do not block on it |
| Gate tool not available | Mark as ⚠️ Skip with justification |

## Adapting to Project Tooling

Not all projects have every tool configured. Adapt the gates:

| Tool | Available? | Alternative |
|------|-----------|-------------|
| mypy / pyright | No | Skip Gate 2, rely on IDE type checking |
| ruff / flake8 | No | Skip Gate 3, do manual style review in Gate 6 |
| pytest | No | Run whatever test framework exists |
| pip-audit / safety | No | Skip Gate 5 automated scan, do manual review |

The minimum viable loop is: **Build → Tests → Diff Review** (Gates 1, 4, 6).
