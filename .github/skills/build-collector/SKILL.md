---
name: build-collector
description: >
  Use this skill when creating a new macroeconomic data collector repository
  from scratch. The skill produces a repository whose layout, schema, and code
  style match the pilot (`collector_banxico_encuesta`) exactly — only the
  source-specific extract logic changes. The agent must complete every phase
  before declaring the collector ready.
---

# Build Collector — Recreate the Pilot for a New Source

This skill walks through generating a new collector repo that is structurally
identical to the pilot. The pilot is the contract; this skill is the
checklist.

**Before you start, read:**

- `.github/copilot-instructions.md` — the canonical guidelines (layout,
  schema, style, anti-patterns).
- The pilot's `main.py` and `scripts/*.py` — the code you will be cloning.

**Core rule:** if you find yourself inventing a new module, a new directory,
or a new abstraction, stop. Look at the pilot. Either the pilot has the
pattern (use it), or the pattern doesn't exist (you don't need it).

---

## Inputs

The user will provide:

1. **SOURCE** — short identifier of the data agency (e.g. `BANXICO`, `IBGE`,
   `FRED`, `ECB`).
2. **DATASET** — short identifier of the specific dataset within that source
   (e.g. `ENCUESTA`, `SIDRA_TABLE_1737`, `CONSUMER_PRICE_INDEX`).
3. **SOURCE_NAME** / **RELEASE_NAME** — human-readable names for metadata.
4. **COUNTRY** — ISO 3-letter code or currency code that goes in
   `metadata.country`.
5. **API/SOURCE_DOCS_URL** — link to the official documentation.
6. **TARGET_SERIES** — the list of series to collect, including the source's
   native IDs.
7. **AUTH** — none, API key (with env var name), or other.

If any of these are missing, ask before proceeding.

---

## Phase 1 — Bootstrap the Repo

### 1.1 Create the directory

The repo name must be `collector_<source>_<dataset>` in lowercase
snake_case. The schema name in `config.py` must match.

```
collector_banxico_encuesta/
collector_ibge_sidra1737/
collector_fred_cpi/
```

### 1.2 Copy the pilot's scaffolding

Create these files, copying byte-for-byte from the pilot then editing only
where called out below:

| File                  | Action                                                                  |
| --------------------- | ----------------------------------------------------------------------- |
| `.gitignore`          | Copy as-is.                                                             |
| `.env.example`        | Copy; remove anything not relevant to the new source.                   |
| `pyproject.toml`      | Copy; update `name`, `description`, drop unneeded deps.                 |
| `requirements.txt`    | Copy; drop deps the new source doesn't need (e.g. `openpyxl`).          |
| `README.md`           | Copy; rewrite the title and the one-paragraph summary. Keep Quickstart. |
| `.vscode/launch.json` | Copy as-is.                                                             |
| `.vscode/settings.json` | Copy as-is.                                                           |
| `scripts/__init__.py` | Empty file.                                                             |

### 1.3 Verify the structure

After this phase the tree must look exactly like the layout in
`copilot-instructions.md` §1. Anything else is wrong.

---

## Phase 2 — `config.py`

Copy the pilot's `scripts/config.py`. Edit only:

- `SCHEMA_NAME` → the new repo name (must match the directory).
- `DEFAULT_START_DATE` default → the earliest date the source actually offers
  (or `"1999-01-01"` as a safe fallback).
- `START_DATE_LOOKBACK_MONTHS` → keep at `5` unless the source has a longer
  revision window.
- HTTP knobs (`REQUEST_TIMEOUT`, `DOWNLOAD_DELAY`, `MAX_RETRIES`) — only
  change if the source documents specific rate limits.

Do **not**:

- Add a new env var unless the source genuinely requires one.
- Add `python-dotenv`. The 10-line manual parser stays.
- Move `SCHEMA_NAME` somewhere else.

---

## Phase 3 — `db.py` and `init_db.py`

Copy `scripts/db.py` byte-for-byte. The only thing that changes is the
catalog/schema constants imported from `config.py`.

Copy `scripts/init_db.py` byte-for-byte. The DDL is **identical across all
collectors**. If you feel tempted to add or change a column in the
standardized tables, stop — that change must be discussed with the user
before touching this file, because it impacts every other collector.

---

## Phase 4 — `extract.py` (the only source-specific work)

This is where 90% of the per-collector effort lives.

### 4.1 Get the docs

Run the `get-api-docs` skill for the new source's API/library before writing
any code. Do not infer endpoints from training data.

### 4.2 Define the structured `series_id`

Pick a small set of components that uniquely identify a series within this
collector. Examples:

- Banxico Encuesta: `{TYPE}_{STAT}_{HORIZON}` → `HEADLINE_MEDIA_3`.
- IBGE SIDRA: `{TABLE}_{VARIABLE}_{LOCATION}` → `1737_VAR63_BR`.
- FRED CPI: `{INDICATOR}_{TRANSFORM}` → `CPI_LEVEL`.

Constraints:

- Uppercase, segments joined by `_`.
- Round-trippable: write a `parse_series_id()` helper that returns a tuple of
  decoded fields.
- `metadata.py` will derive `name`, `description`, and `unit` from this
  decomposition. Do not store hand-written names in a hardcoded mapping.

### 4.3 Implement the extract module

Mirror the pilot's structure:

1. Top: source constants (`SOURCE_NAME`, `BASE_URL`, parsing layout, code
   maps).
2. `parse_series_id()` helper — used by `metadata.py`.
3. `_http_get(client, url, params)` — exponential-backoff retry wrapper.
   Keep this near-identical to the pilot.
4. `_build_client()` — returns an `httpx.Client` with `REQUEST_TIMEOUT`,
   `USER_AGENT`, `trust_env=True`, `follow_redirects=False`.
5. Source-specific fetch + parse functions.
6. `collect_raw_data(start_date)` → `dict[date, dict[str, float | None]]`.

Behavior contract:

- One bad date or one schema mismatch logs a warning and is skipped — it
  does not abort the run.
- A hard failure (auth, total network outage) propagates.
- Progress is logged every ~10 dates.

### 4.4 What `collect_raw_data` returns

Always: `{reference_date: {series_id: value | None}}`. Both `metadata.py`
and `time_series.py` consume exactly this shape. Do not change it.

---

## Phase 5 — `metadata.py`

Copy from the pilot. The structure is universal; only one function is
source-specific:

- `_series_descriptive_row(series_id)` — uses `parse_series_id` from
  `extract.py` to build `name`, `description`, `country`, `frequency`, `unit`.

Edit that function so the strings match the new source's vocabulary. Leave
`build_metadata_rows`, `upsert_metadata`, and the SQL constants alone.

The `_COMPARABLE_COLUMNS` tuple stays identical. `collected_at` is excluded
from the comparison so unchanged rows keep their old timestamp — this is
deliberate.

---

## Phase 6 — `time_series.py` and `run_logs.py`

Copy both byte-for-byte. They are completely source-agnostic.

Verify after copying:

- `BATCH_SIZE = 500` and `ROUND_DECIMALS = 10` are unchanged unless the
  source has a documented reason (very noisy floats, very large batches that
  break the driver).
- `get_max_reference_date` is exported — `main.py` imports it.

---

## Phase 7 — `main.py`

Copy from the pilot. Edit only:

- The module docstring (one paragraph naming the new source).
- The `argparse` description string.
- The first INFO log message (`"Starting <source> collector"`).

Verify the orchestration order is unchanged:

1. `_setup_logging` (dual stdout + buffer handler).
2. `build_engine()` → `init_db(engine)`.
3. `_resolve_start_date(...)` (rewind from latest, or fall back to default).
4. `collect_raw_data(start_date)`.
5. `upsert_metadata(...)`.
6. `upsert_time_series(...)`.
7. `try/except/finally` writes one row to `logs` regardless of outcome.

Remove the `sys.argv.append(...)` debug line at the bottom of the pilot's
`main.py` — that is a developer convenience, not part of the contract.

---

## Phase 8 — Verification

Run through this checklist before declaring the collector ready. Every box
must be checkable.

### Layout

- [ ] Repo name is `collector_<source>_<dataset>`, lowercase snake_case.
- [ ] Top-level files: `.env.example`, `.gitignore`, `README.md`, `main.py`,
      `pyproject.toml`, `requirements.txt`. No others.
- [ ] `scripts/` contains exactly: `__init__.py`, `config.py`, `db.py`,
      `extract.py`, `init_db.py`, `metadata.py`, `run_logs.py`,
      `time_series.py`. No others.
- [ ] No `tests/`, `core/`, `lib/`, `utils/`, `common/`, `Dockerfile`,
      `Makefile`, or CI workflow files (unless the user asked).

### Schema

- [ ] `SCHEMA_NAME` in `config.py` matches the repo name.
- [ ] DDL in `init_db.py` is byte-identical to the pilot's DDL.
- [ ] No new columns added to `metadata`, `time_series`, or `logs`.

### Code style

- [ ] Every module starts with `from __future__ import annotations`.
- [ ] Every function has type hints.
- [ ] No `print` statements outside `__main__`.
- [ ] No `requests`, `python-dotenv`, ORM models, or migration tools added.
- [ ] No `BaseCollector` or other base class.
- [ ] All SQL via `sqlalchemy.text(...)` and named parameters.

### Behavior

- [ ] `python -m scripts.init_db` creates the schema and tables on a fresh
      local DB.
- [ ] `python main.py --start-date <recent-date>` runs end-to-end with no
      errors and writes rows to all three tables.
- [ ] Running `python main.py` a second time produces zero new metadata
      writes and zero new vintage rows (idempotent).
- [ ] A run that fails mid-pipeline still writes one row to `logs` with
      `status='error'` and a populated `traceback`.

### Output sanity

- [ ] Every series in `metadata` has `observation_count > 0` and matching
      `first_observation` / `last_observation`.
- [ ] In `time_series`, every `(series_id, reference_date)` has at least one
      row. Baselines carry `vintage_date = today` (the collection date), so
      `vintage_date >= reference_date` should hold for every row except a
      future-dated observation.
- [ ] No NaN, no infinities in `value`. `None` rows are dropped before
      insert.

If any box is unchecked, fix it before handing off. Do not declare done with
caveats.

---

## Anti-Patterns to Reject

These come up every time. Recognize them and push back.

- **"I'll add a `core/` directory to share code with the next collector."**
  No. Each collector is self-contained. Duplicate the 30 lines.
- **"Let me write a `BaseCollector` that the new one inherits from."**
  No. The pilot has no inheritance and no plugins.
- **"I'll use `pydantic` to validate the parsed data."**
  No. A plain dict + a few `if value is None: continue` checks is the
  pattern.
- **"I'll add a `tests/` folder with one trivial test."**
  No. Add tests only when the logic genuinely warrants them.
- **"This source serves JSON, so I'll add `requests`."**
  No. `httpx` handles JSON natively.
- **"I'll factor `extract.py` into `fetch.py`, `parse.py`, `client.py`."**
  Only if the file exceeds ~400 lines. Below that, one file is correct.
- **"Let me add `python-dotenv` so the `.env` parser is more robust."**
  No. The manual parser is intentional.

---

## Done Definition

The collector is done when:

1. All Phase 8 boxes are ticked.
2. The repo is structurally indistinguishable from the pilot — a reader
   familiar with the pilot can navigate the new repo without surprises.
3. Two consecutive `python main.py` runs against a fresh DB produce a fully
   populated set of three standardized tables on the first run, and zero
   writes on the second run.

Hand off to the user with: a short summary of what was collected (number of
series, first/last observation dates), and the SQL query they can run to
inspect the result.
