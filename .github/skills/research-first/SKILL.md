---
name: research-first
description: Use before writing custom code. Check existing codebase, shared utilities, and external libraries to avoid reinventing solutions.
---

# Research First

Before writing new code, systematically check whether a solution already exists. This prevents duplicate implementations, leverages battle-tested code, and keeps the codebase lean.

## When to Use

- Before implementing any utility function
- Before adding a new dependency
- Before building infrastructure (logging, config, HTTP clients, etc.)
- When a task feels like "someone must have solved this before"

## Search Order

Follow this sequence. Stop as soon as you find a suitable solution.

### 1. Check Current Codebase

Search the broader codebase for existing implementations:

```
- Search for function names related to your task
- Search for import statements of relevant libraries
- Check if another module already solves a similar problem
```

If you find a function that does 80%+ of what you need, extend it rather than creating a new one.

### 2. Check Installed Dependencies

Before adding a new package, check what's already available:

```bash
pip list | grep -i <keyword>
```

Many common tasks are already covered by installed packages.

### 3. Check External Libraries

If no internal solution exists, research external options before writing custom code:

- Use `chub` MCP tools or the `get-api-docs` skill for up-to-date API documentation
- Prefer well-maintained libraries with active communities
- Consider the dependency's size and transitive dependencies

### 4. Write Custom Code (Last Resort)

If writing new code is necessary:

- **If the function is reusable** — add it to the appropriate shared module (see step 1)
- **If the function is domain-specific** — implement it locally in the module that needs it
- Document why existing solutions were insufficient

## Decision Criteria

| Question | If Yes | If No |
|----------|--------|-------|
| Does a shared module function do this? | Use it | Continue to step 2 |
| Does another module in the codebase do this? | Import it or extract to shared | Continue to step 3 |
| Does an installed package cover this? | Use it | Continue to step 4 |
| Does a well-known library solve this? | Consider adding dependency | Write custom code |
| Is the custom code reusable? | Add to shared modules | Implement locally |

## Anti-Patterns

- **NIH (Not Invented Here):** Writing custom JSON parsing, HTTP retry logic, date formatting when standard libraries handle it
- **Dependency bloat:** Adding a large package for one small function — write the small function instead
- **Hidden duplication:** Implementing a helper in a local module when the same logic exists elsewhere in the codebase
- **Stale knowledge:** Assuming a library doesn't support a feature without checking current docs

## Integration with MainFunctionsLocation

This skill complements the `MainFunctionsLocation.instructions.md` rule. That instruction tells you *where* to put new shared functions. This skill tells you *when* to look before writing them.
