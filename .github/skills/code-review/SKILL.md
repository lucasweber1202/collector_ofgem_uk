---
name: code-review
description: Use when completing tasks, implementing major features, or before merging to verify work meets requirements. Catches issues before they cascade.
---

# Requesting Code Review

Request code review to catch issues before they cascade.

**Core principle:** Review early, review often.

## When to Request Review

**Mandatory:**
- After completing major feature
- Before merge to main
- After completing implementation plan

**Optional but valuable:**
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bug
- When uncertain about approach

## Self-Review Checklist

Before requesting review, verify:

### Functionality
- [ ] All acceptance criteria met
- [ ] Edge cases handled
- [ ] Error handling in place
- [ ] No silent failures

### Code Quality
- [ ] Follows existing patterns in codebase
- [ ] No duplicate code (DRY)
- [ ] No unnecessary features (YAGNI)
- [ ] Clear naming (variables, functions, classes)
- [ ] Comments explain "why" not "what"

### Testing
- [ ] All new code has tests
- [ ] Tests follow TDD (written first)
- [ ] Edge cases tested
- [ ] Error cases tested
- [ ] All tests pass

### Documentation
- [ ] Public APIs documented
- [ ] Complex logic explained
- [ ] README updated if needed
- [ ] CHANGELOG updated if applicable

## How to Request Review

**1. Summarize what was implemented:**

```markdown
## Changes
- Added email validation to user registration
- Created validators.py module
- Added 12 unit tests covering valid/invalid cases

## Files Changed
- src/user/validators.py (new)
- src/user/registration.py (modified lines 45-67)
- tests/unit/test_validators.py (new)

## Testing
- All 12 new tests pass
- Existing 45 tests still pass
- Coverage: 94% on new code
```

**2. Highlight areas of concern:**

```markdown
## Areas for Review
- Is the regex pattern for email validation comprehensive enough?
- Should we add rate limiting to the registration endpoint?
- Edge case: emails with + symbols - currently allowed, is that correct?
```

**3. Provide context:**

```markdown
## Context
- Spec: docs/specs/2025-01-15-user-validation-design.md
- Related issue: #123
- Depends on: PR #120 (auth module)
```

## Review Response Guidelines

When receiving review feedback:

### Critical Issues
- Fix immediately
- Don't proceed until resolved
- Examples: security vulnerabilities, data loss risks, breaking changes

### Important Issues
- Fix before merging
- May proceed with other work while fixing
- Examples: missing tests, unclear naming, performance issues

### Minor Issues
- Note for future improvement
- Can merge with these present
- Examples: style preferences, optional optimizations

### Responding to Feedback

**If you agree:**
```
Good catch. Fixed in commit abc123.
```

**If you disagree:**
```
I see the concern, but I chose this approach because [reasoning].
The alternative would [trade-off]. Happy to discuss further.
```

**If you need clarification:**
```
Could you elaborate on what you mean by [specific point]?
I want to make sure I address the right concern.
```

## Review Focus Areas

### Security
- Input validation
- Authentication/authorization
- SQL injection prevention
- XSS prevention
- Sensitive data handling

### Performance
- N+1 queries
- Unnecessary database calls
- Memory leaks
- Algorithmic complexity

### Maintainability
- Clear abstractions
- Single responsibility
- Testability
- Documentation

### Reliability
- Error handling
- Graceful degradation
- Logging
- Monitoring hooks

## Severity-Based Detection Checklist

When reviewing code, classify findings by severity. Report **only** findings you are confident about (≥80% confidence). Do not fabricate issues.

### 🔴 CRITICAL — Must fix before merge

| Pattern | What to Look For |
|---------|-----------------|
| Hardcoded secrets | API keys, passwords, tokens in source code |
| Injection | Unsanitized input in SQL, shell commands, `eval()`, `exec()` |
| Auth bypass | Missing permission checks on endpoints or data access |
| Data exposure | Logging or returning sensitive fields (PII, credentials) |
| Path traversal | User-controlled paths without validation (`../` attacks) |
| Unsafe deserialization | `pickle.loads()`, `yaml.load()` without `SafeLoader` |

### 🟠 HIGH — Should fix before merge

| Pattern | What to Look For |
|---------|-----------------|
| Missing input validation | No validation at system boundaries (API inputs, file reads) |
| Unhandled exceptions | Bare `except:` or `except Exception` that swallows errors silently |
| Resource leaks | Files, connections, cursors opened without `with` or `finally` |
| N+1 queries | Database queries inside loops |
| Large functions | Functions >50 lines — likely need decomposition |
| Missing tests | New logic paths without corresponding test coverage |

### 🟡 MEDIUM — Fix or justify

| Pattern | What to Look For |
|---------|-----------------|
| Deep nesting | >4 levels of indentation — extract helper or use early return |
| Mutation in loops | Modifying a collection while iterating over it |
| Magic numbers | Unexplained numeric literals — extract to named constants |
| Dead code | Unreachable branches, commented-out blocks, unused imports |
| Poor naming | Single-letter variables outside comprehensions, misleading names |
| Missing type hints | Public function signatures without type annotations |

### 🟢 LOW — Note for future

| Pattern | What to Look For |
|---------|-----------------|
| Debug artifacts | `print()`, `console.log`, `breakpoint()` left in code |
| TODOs without tracking | `TODO`/`FIXME` comments without linked issue |
| Style inconsistency | Deviations from project conventions (naming, formatting) |
| Optional optimization | Obvious performance improvements that don't affect correctness |

### Review Summary Format

After reviewing, produce a summary table:

```markdown
| Severity | Count | Key Findings |
|----------|-------|-------------|
| 🔴 CRITICAL | 0 | — |
| 🟠 HIGH | 1 | Missing input validation on `/api/upload` |
| 🟡 MEDIUM | 2 | Magic numbers in scoring.py; deep nesting in parser.py |
| 🟢 LOW | 1 | Debug print in utils.py |

**Verdict:** 🟡 Approve with changes (fix HIGH before merge)
```

### Approval Criteria

| Verdict | Condition |
|---------|-----------|
| ✅ Approve | No CRITICAL or HIGH findings |
| 🟡 Approve with changes | No CRITICAL; HIGH findings are minor and tracked |
| ❌ Request changes | Any CRITICAL finding, or multiple unaddressed HIGH findings |

## Red Flags

**Never:**
- Skip review because "it's simple"
- Ignore Critical issues
- Proceed with unfixed Important issues
- Argue without technical reasoning

**Do:**
- Push back with technical reasoning if reviewer is wrong
- Show code/tests that prove implementation works
- Request clarification if feedback is unclear
- Thank reviewers for catching issues

## Example Review Request

```markdown
## Code Review Request: User Email Validation

### Summary
Added email validation to user registration per spec in docs/specs/2025-01-15-user-validation-design.md

### Changes
- `src/user/validators.py` - New validation module
- `src/user/registration.py` - Integrated validation (lines 45-67)
- `tests/unit/test_validators.py` - 12 new tests

### Testing Status
- ✅ All 12 new tests pass
- ✅ All 45 existing tests pass
- ✅ Manual testing completed on local env
- Coverage: 94% on new code

### Areas for Review
1. Email regex pattern - comprehensive enough?
2. Error messages - user-friendly?
3. Integration point - cleanest approach?

### Open Questions
- Should we validate email domain exists (DNS lookup)?
- Rate limiting consideration for registration endpoint?

### How to Test
```bash
pytest tests/unit/test_validators.py -v
python -c "from src.user.validators import validate_email; print(validate_email('test@example.com'))"
```
```

## Post-Review Workflow

1. **Receive feedback**
2. **Categorize by severity** (Critical/Important/Minor)
3. **Fix Critical issues immediately**
4. **Fix Important issues before merge**
5. **Note Minor issues for future**
6. **Re-request review if significant changes made**
7. **Merge when approved**

## Integration with Development Flow

**During Implementation:**
- Self-review after each task
- Request review after completing plan

**Before Merge:**
- Final review pass
- Verify all feedback addressed
- Run full test suite
- Update documentation

**After Merge:**
- Monitor for issues
- Address any post-merge feedback
- Document lessons learned
