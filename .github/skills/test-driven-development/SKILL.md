---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code. Enforces RED-GREEN-REFACTOR discipline.
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## When to Use

**Always:**
- New features
- Bug fixes
- Refactoring
- Behavior changes

**Exceptions (ask user first):**
- Throwaway prototypes
- Generated code
- Configuration files

Thinking "skip TDD just this once"? Stop. That's rationalization.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

**No exceptions:**
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete

Implement fresh from tests. Period.

## Red-Green-Refactor Cycle

### RED - Write Failing Test

Write one minimal test showing what should happen.

**Good:**
```python
def test_retries_failed_operations_3_times():
    attempts = []
    
    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise Exception('fail')
        return 'success'
    
    result = retry_operation(operation)
    
    assert result == 'success'
    assert len(attempts) == 3
```

**Bad:**
```python
def test_retry_works():
    mock = Mock(side_effect=[Exception(), Exception(), 'success'])
    retry_operation(mock)
    assert mock.call_count == 3  # Tests mock, not code
```

**Requirements:**
- One behavior
- Clear name
- Real code (no mocks unless unavoidable)

### Verify RED - Watch It Fail

**MANDATORY. Never skip.**

```bash
pytest path/to/test.py -v
```

Confirm:
- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)

**Test passes?** You're testing existing behavior. Fix test.
**Test errors?** Fix error, re-run until it fails correctly.

### GREEN - Minimal Code

Write simplest code to pass the test.

**Good:**
```python
def retry_operation(fn, max_retries=3):
    for i in range(max_retries):
        try:
            return fn()
        except Exception:
            if i == max_retries - 1:
                raise
```

**Bad:**
```python
def retry_operation(
    fn,
    max_retries=3,
    backoff='linear',
    on_retry=None,
    timeout=None,  # YAGNI
):
    # Over-engineered
```

Don't add features, refactor other code, or "improve" beyond the test.

### Verify GREEN - Watch It Pass

**MANDATORY.**

```bash
pytest path/to/test.py -v
```

Confirm:
- Test passes
- Other tests still pass
- Output pristine (no errors, warnings)

**Test fails?** Fix code, not test.
**Other tests fail?** Fix now.

### REFACTOR - Clean Up

After green only:
- Remove duplication
- Improve names
- Extract helpers

Keep tests green. Don't add behavior.

### Repeat

Next failing test for next feature.

## Good Tests

| Quality | Good | Bad |
|---------|------|-----|
| **Minimal** | One thing. "and" in name? Split it. | `test_validates_email_and_domain_and_whitespace` |
| **Clear** | Name describes behavior | `test_test1` |
| **Shows intent** | Demonstrates desired API | Obscures what code should do |

## Why Order Matters

**"I'll write tests after to verify it works"**

Tests written after code pass immediately. Passing immediately proves nothing:
- Might test wrong thing
- Might test implementation, not behavior
- Might miss edge cases you forgot
- You never saw it catch the bug

Test-first forces you to see the test fail, proving it actually tests something.

**"I already manually tested all the edge cases"**

Manual testing is ad-hoc. You think you tested everything but:
- No record of what you tested
- Can't re-run when code changes
- Easy to forget cases under pressure
- "It worked when I tried it" ≠ comprehensive

Automated tests are systematic. They run the same way every time.

**"Deleting X hours of work is wasteful"**

Sunk cost fallacy. The time is already gone. Your choice now:
- Delete and rewrite with TDD (X more hours, high confidence)
- Keep it and add tests after (30 min, low confidence, likely bugs)

The "waste" is keeping code you can't trust.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Already manually tested" | Ad-hoc ≠ systematic. No record, can't re-run. |
| "Deleting X hours is wasteful" | Sunk cost fallacy. Keeping unverified code is technical debt. |
| "Keep as reference, write tests first" | You'll adapt it. That's testing after. Delete means delete. |
| "Need to explore first" | Fine. Throw away exploration, start with TDD. |
| "Test hard = design unclear" | Listen to test. Hard to test = hard to use. |
| "TDD will slow me down" | TDD faster than debugging. |
| "Manual test faster" | Manual doesn't prove edge cases. You'll re-test every change. |

## Red Flags - STOP and Start Over

- Code before test
- Test after implementation
- Test passes immediately
- Can't explain why test failed
- Tests added "later"
- Rationalizing "just this once"
- "I already manually tested it"
- "Tests after achieve the same purpose"
- "Keep as reference" or "adapt existing code"

**All of these mean: Delete code. Start over with TDD.**

## Verification Checklist

Before marking work complete:

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for expected reason (feature missing, not typo)
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass
- [ ] Output pristine (no errors, warnings)
- [ ] Tests use real code (mocks only if unavoidable)
- [ ] Edge cases and errors covered

Can't check all boxes? You skipped TDD. Start over.

## When Stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write wished-for API. Write assertion first. Ask user. |
| Test too complicated | Design too complicated. Simplify interface. |
| Must mock everything | Code too coupled. Use dependency injection. |
| Test setup huge | Extract helpers. Still complex? Simplify design. |

## Debugging Integration

Bug found? Write failing test reproducing it. Follow TDD cycle. Test proves fix and prevents regression.

## Numerical / Quantitative TDD

Standard TDD verifies Boolean correctness (pass/fail). Numerical code requires **quantitative correctness** — the right values, within tolerance.

### DGP-First Workflow

For any code that estimates parameters, fits models, or transforms numerical data:

1. **Define a known Data-Generating Process (DGP)** — pick ground-truth parameter values
2. **Generate synthetic data** from the DGP with a fixed random seed
3. **Write a failing test** that asserts the pipeline recovers the known parameters
4. **Implement the estimation/transformation code**
5. **Verify recovery** — parameters within tolerance of ground truth

### Example Pattern

```python
def test_ar1_estimation_recovers_known_parameters():
    """Generate AR(1) data with known phi, estimate, verify recovery."""
    np.random.seed(42)
    
    # Known DGP: AR(1) with phi=0.8, sigma=1.0
    true_phi = 0.8
    T = 1000
    y = np.zeros(T)
    for t in range(1, T):
        y[t] = true_phi * y[t-1] + np.random.normal(0, 1.0)
    
    # Run estimation pipeline
    result = estimate_ar1(y)
    
    # Verify recovery (not exact — tolerance-based)
    assert result.phi == pytest.approx(true_phi, abs=0.05)
```

### Tolerance Guidelines

| Context | Assertion | Example |
|---------|-----------|---------|
| Deterministic math | Tight tolerance | `np.allclose(result, expected, atol=1e-10)` |
| Estimated parameters (large sample) | Moderate tolerance | `pytest.approx(true_value, abs=0.05)` |
| MCMC / stochastic | Statistical bounds | `abs(posterior_mean - true) < 2 * posterior_std` |
| Relative accuracy | Relative tolerance | `np.allclose(result, expected, rtol=1e-2)` |

### Stochastic Code

For MCMC, bootstrap, or simulation-based code:

- **Fixed seeds in tests** — `np.random.seed(42)` for reproducibility
- **Statistical assertions** — "posterior mean within 2 SE of true value"
- **Multiple runs** — if seed-dependent, run N times and assert success rate > 90%

### Anti-Patterns (Numerical)

| Anti-Pattern | Why It's Bad | Do Instead |
|--------------|-------------|------------|
| `assert result is not None` | Proves nothing about correctness | Assert values match known DGP |
| `assert result.shape == (100, 3)` | Shape can be right with wrong numbers | Check shape AND values |
| `assert result == 0.8` | Exact float equality fails randomly | Use `pytest.approx` or `np.allclose` |
| Mocking the computation | Tests the mock, not the math | Use real computation on synthetic data |
| "Math is too complex to test" | Complex math is exactly what needs testing | Use known DGP to make it testable |

Never fix bugs without a test.

## Final Rule

```
Production code → test exists and failed first
Otherwise → not TDD
```

No exceptions without user's explicit permission.
