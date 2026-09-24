---
name: planning-and-design
description: Use BEFORE implementing any feature, writing code, or executing a multi-step task. Converts ideas or specs into structured implementation plans and presents them for approval.
---

# Planning and Design

## Core Principle

Always design the solution before implementing anything.

The agent must **never start coding, modifying files, or executing tasks** before presenting a proposed design or implementation plan and receiving user approval.

All proposed plans must be presented using the **#planReview tool**.

The **main orchestrating agent** must also **use the #askUser tool before finishing any run**, even if only to confirm that the task is complete or to resolve an important uncertainty.

> **Sub-agent exception:** If you are running as a sub-agent (invoked via `runSubagent`), do **NOT** call `#askUser` or `#planReview`. Return your results directly to the orchestrator.

---

# Mandatory Workflow

Follow this workflow strictly (applies to the **main orchestrating agent only**):

1. **Understand the request**
2. **Clarify requirements if necessary**
3. **Design the solution**
4. **Present the plan using #planReview**
5. **Wait for approval**
6. **Execute the plan**
7. **Before finishing the run, call #askUser**

Under no circumstances should the main orchestrating agent complete the run without using **#askUser**.

> Sub-agents skip steps 4, 5, and 7 — they do not present plans or ask the user for confirmation.

---

# Step 1 — Understand the Problem

Determine:

- The user's goal
- Functional requirements
- Constraints
- Expected outputs
- Whether the task affects multiple subsystems

If the request is ambiguous or missing critical information, ask questions.

For important uncertainties or missing inputs, use **#askUser**.

---

# Step 2 — Scope and Decomposition

Break the problem into clear components.

Check whether the task should be split into independent subprojects.

If multiple independent systems are involved, propose separate plans.

Prefer solutions that follow:

- DRY (Don't Repeat Yourself)
- YAGNI (You Aren't Gonna Need It)
- Small, well-defined modules
- Clear responsibilities per file

---

# Step 3 — Design the Solution

Before implementation, define:

- System architecture
- File structure
- Responsibilities of each component
- Dependencies between tasks
- Testing approach
- Validation and error handling

Assume the implementer:

- Is a capable developer
- Has minimal context about the project
- Needs explicit instructions

Designs should be explicit and self-contained.

---

# Step 4 — Create the Implementation Plan

Plans should be structured into **small, atomic tasks**.

Each task should represent a small amount of work (2–5 minutes).

Example steps:

- Write failing test
- Run test to confirm failure
- Implement minimal code
- Run tests
- Commit

Tasks should clearly specify:

- Files to create
- Files to modify
- Tests to add
- Commands to run
- Expected outcomes

Prefer **test-driven development (TDD)** when applicable.

---

# Plan Structure

All plans should follow this format:

```

# [Feature Name] Implementation Plan

**Goal:** [One sentence describing what this builds]

**Architecture:** [2–3 sentences describing the approach]

**Tech Stack:** [Key tools or frameworks]

**Related Spec:** [If applicable]

---

### Task 1: [Component]

Files:

* Create: path/to/file
* Modify: path/to/file
* Test: path/to/test

Steps:

1. Write failing test
2. Run test and confirm failure
3. Implement minimal solution
4. Run tests and confirm success
5. Commit

```

Tasks should also list dependencies when necessary.

---

# Phased Delivery

For non-trivial features, organize tasks into delivery phases. Each phase should produce working, testable code.

```
Phase 1: MVP        → Minimal working version (happy path only)
Phase 2: Core       → Full feature coverage (all requirements)
Phase 3: Edge Cases → Error handling, validation, boundary conditions
Phase 4: Polish     → Performance, documentation, cleanup
```

**Rules:**
- Each phase must leave the codebase in a passing-tests state
- Present the plan with phases clearly marked
- The user may approve only Phase 1 initially and review before continuing
- Skip phases that don't apply (e.g., a simple bugfix may only need Phase 1)

**Example phased task grouping:**

```markdown
## Phase 1: MVP
- Task 1: Create data model with basic fields
- Task 2: Add API endpoint (happy path)
- Task 3: Write tests for happy path

## Phase 2: Core
- Task 4: Add validation rules
- Task 5: Add error responses
- Task 6: Write tests for validation

## Phase 3: Edge Cases
- Task 7: Handle concurrent access
- Task 8: Add rate limiting
- Task 9: Write tests for edge cases
```

---

# Sizing and Red Flags

Before presenting a plan, assess its size:

| Size | Tasks | Guidance |
|------|-------|----------|
| Small | 1–3 | Single phase, implement directly |
| Medium | 4–10 | Split into 2 phases (MVP + Core) |
| Large | 11–20 | Split into 3–4 phases, consider sub-plans |
| Too Large | 20+ | Decompose into independent sub-projects with separate plans |

**Red flags — reconsider the plan if:**
- A single task takes more than 10 minutes
- The plan requires modifying more than 10 files
- Dependencies between tasks form a cycle
- The plan requires technologies or APIs you haven't verified exist
- The plan duplicates functionality that already exists (use `research-first` skill)

---

# Code Quality Principles

Implementation plans must encourage:

- Clear naming
- Small functions
- Single responsibility
- Testable design
- Explicit error handling
- Minimal duplication

Avoid unnecessary complexity.

---

# Code Review Mindset

Before considering a plan complete, mentally check:

### Functionality
- Acceptance criteria covered
- Edge cases handled
- Error handling included

### Code Quality
- No unnecessary duplication
- Naming clarity
- Logical structure

### Testing
- Tests for expected behavior
- Tests for edge cases
- Tests for failure scenarios

### Maintainability
- Clear abstractions
- Minimal coupling
- Documentation where necessary

---

# Presenting the Plan

Once the design is ready:

Use **#planReview** to present the full proposal.

The plan should clearly explain:

- What will be built
- How it will be built
- The main tasks involved

Do not begin implementation until the user approves the plan.

---

# During Execution

While executing an approved plan:

- Follow tasks sequentially
- Validate each step
- Run tests frequently
- Commit frequently
- If a major design issue appears, pause and propose an updated plan

For significant uncertainty or blocking issues, use **#askUser**.

---

# Completion Rule

Before finishing the run:

The agent **must call #askUser**.

This ensures the user can:

- Confirm completion
- Request modifications
- Provide feedback
- Approve final results

The agent must **never end a run without using #askUser**.

---

# Summary

Always follow this sequence:

1. Understand the request
2. Clarify requirements if needed
3. Design the solution
4. Present the plan using **#planReview**
5. Wait for approval
6. Execute the tasks
7. Before finishing, call **#askUser**

Design first. Implement second.
```
