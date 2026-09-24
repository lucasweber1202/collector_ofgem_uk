---
description: Onboard a new macroeconomic data source as a standalone collector repository, following the pilot architecture.
agent: agent
---

# Onboard New Source

You are creating a new collector repository for a macroeconomic data source.
Each source gets its **own self-contained repository** named
`collector_<source>_<dataset>` and structured exactly like the pilot
(`collector_banxico_encuesta`).

Follow the `build-collector` skill at
`.github/skills/build-collector/SKILL.md` end-to-end. Complete every phase.
Do not declare done until all Phase 8 verification boxes are ticked.

## Reference files (read before writing code)

- `.github/copilot-instructions.md` — canonical guidelines: layout, schema,
  style, anti-patterns.
- `.github/skills/build-collector/SKILL.md` — the eight-phase workflow.
- `.github/skills/series-selection/SKILL.md` — rules for choosing what
  series to include.
- The pilot's `main.py` and `scripts/*.py` — the code you will be cloning.

## Inputs the user must provide

- **SOURCE** — short identifier of the agency (e.g. `BANXICO`, `IBGE`, `FRED`).
- **DATASET** — short identifier of the specific dataset
  (e.g. `ENCUESTA`, `SIDRA1737`, `CPI`).
- **SOURCE_NAME** / **RELEASE_NAME** — human-readable names for `metadata`.
- **COUNTRY** — ISO 3-letter or currency code for `metadata.country`.
- **DOCS_URL** — link to the official documentation.
- **TARGET_SERIES** — the list of series to collect, including the source's
  native IDs. Run `series-selection` if the list isn't already curated.
- **AUTH** — none, API key (with env var name), or other.

If anything is missing, ask before generating files.

## Constraints

- **Repo name = schema name.** `collector_<source>_<dataset>` in lowercase
  snake_case. Set `SCHEMA_NAME` in `scripts/config.py` to match.
- **Three tables only.** `metadata`, `time_series`, `logs` — DDL byte-identical
  to the pilot's `scripts/init_db.py`. Do not add columns.
- **Self-contained.** Copy the pilot's eight scripts into the new repo;
  do not import from a shared package. Edit only what the new source
  requires (mainly `extract.py`, plus tiny touches in `config.py`,
  `metadata.py`, `main.py`).
- **No new dependencies** beyond what `extract.py` actually needs. If the
  source serves JSON, `httpx` is enough — do not add `requests`. If the
  source doesn't serve Excel, drop `openpyxl` from the pilot's
  `requirements.txt`.
- **`series_id` is structured and parseable.** Define a
  `parse_series_id()` helper in `extract.py`; `metadata.py` derives
  `name`, `description`, and `unit` from it. No hand-written name dicts.
- **Idempotent.** Two consecutive runs against the same DB must produce
  zero new metadata writes and zero new vintage rows on the second run.
- **Use `get-api-docs`** before writing `extract.py`. Do not infer source
  endpoints from training data.

## Anti-patterns to refuse

- A `BaseCollector` class, plugin system, or shared `core/` library.
- Adding `python-dotenv`, `requests`, an ORM, or a migration framework.
- A `tests/`, `core/`, `lib/`, `utils/`, `Dockerfile`, `Makefile`, or CI
  workflow file (unless the user explicitly asked).
- Splitting `extract.py` into multiple files when it's under ~400 lines.
- Adding columns to `metadata`, `time_series`, or `logs`.

## Done definition

The collector is done when:

1. The repo is structurally indistinguishable from the pilot.
2. Every Phase 8 box in `build-collector` is checked.
3. A fresh-DB run populates all three standardized tables.
4. The next `python main.py` run is a no-op.
