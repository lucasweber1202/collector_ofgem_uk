---
name: audit-collector
description: >
  Use this skill to verify that a collector's standardized `metadata` and
  `time_series` output is faithful to the official source. This is a
  metadata-correctness audit (are the names, units, scopes, frequencies, and
  values what the source actually publishes?), not a data-quality check.
  Core assumption: the catalog may contain mislabels — verify, do not trust.
---

# Audit Collector — Metadata Verification

This skill defines the workflow for **auditing an existing collector**
against the official source. The collector under audit follows the pilot
architecture (see `.github/copilot-instructions.md`): one source per
repository, with three standardized tables (`metadata`, `time_series`,
`logs`) under a per-collector schema.

**Core principle:** assume nothing. Verify each `series_id` against the
authoritative source — the same API or web page the collector pulls from —
and reconcile what's stored in `metadata` against what the source actually
says.

---

## Inputs

The user will provide:

1. The path to the collector repo to audit.
2. (Optional) a specific `series_id` or set of IDs to focus on. If absent,
   audit the entire `metadata` table.

---

## Phase 1 — Understand the Collector

Before reading any data, understand what this collector claims to produce.

1. Read `.github/copilot-instructions.md` — confirm the collector follows
   the standard layout. If it doesn't, audit the structure first.
2. Read the collector's `scripts/extract.py`. Note:
   - `SOURCE_NAME`, `BASE_URL`, and any code maps.
   - The `parse_series_id()` function — this is the contract between IDs
     and human-readable fields.
3. Read `scripts/metadata.py`'s `_series_descriptive_row()` — that's where
   `name`, `description`, `country`, `frequency`, and `unit` come from.
4. Read the README and `pyproject.toml` for the dataset's official name.

Write a short note (3–5 lines) summarizing what the collector says it
collects. This is your hypothesis. The audit is the test.

---

## Phase 2 — Pull the Stored Metadata

Connect to the collector's database (local or PROD) and dump the metadata
table:

```sql
SELECT series_id, name, description, country, frequency, unit,
       first_observation, last_observation, observation_count
FROM <schema>.metadata
ORDER BY series_id;
```

For each row, build a verification table:

| series_id | Stored name | Stored unit | Stored frequency | Source ground truth (TBD) | Match? |
| --------- | ----------- | ----------- | ---------------- | ------------------------- | ------ |

Leave the "ground truth" column empty for now. Phase 3 fills it in.

---

## Phase 3 — Verify Against the Source

For each `series_id` (or a representative sample if there are hundreds):

1. Decode the ID with `parse_series_id()` to know what the collector
   *claims* it represents.
2. Open the corresponding source page or API endpoint. **Use the same URL
   the collector uses** — that's the audit, not a parallel source.
3. Compare:
   - **Name / scope** — does the source actually call this what the
     collector calls it? Common errors: "national" that's actually
     "urban", "headline" that's actually "core", "seasonally adjusted"
     that's actually raw.
   - **Unit** — `percent` vs `index points` vs `number of responses`.
     Easy to mislabel.
   - **Frequency** — does the source publish monthly, but we wrote
     `quarterly`?
   - **Country / currency** — is the ISO code correct for the source?
   - **First / last observation** — are these plausible for the source?
   - **Sample of values** — pull 2–3 observations from `time_series` for
     this series at recent `reference_date`s and check they match the
     source's published numbers (allow rounding to the source's published
     precision; do not flag a mismatch on the 9th decimal).

For sources that serve Excel or PDF, verify against the actual file the
collector parses. For HTML-table sources, verify against the rendered
page.

---

## Phase 4 — Verify Vintage Behavior (Optional but Strongly Recommended)

For at least one revision-prone series, verify that the vintage logic is
working:

```sql
SELECT reference_date, vintage_date, value
FROM <schema>.time_series
WHERE series_id = '<some_series_id>'
ORDER BY reference_date, vintage_date;
```

Expected pattern:

- Every `(series_id, reference_date)` has at least one row. Baselines
  carry `vintage_date = today` (the collection date), so for a series
  collected in real-time the baseline row's `vintage_date` is close
  to its `reference_date`; for a series with historical backfill,
  baseline `vintage_date` is the day the collector ran.
- Revisions appear as additional rows with later `vintage_date` and
  different `value`.
- Same-day re-runs that change a value UPDATE the existing
  `vintage_date = today` row in place (do not produce a duplicate
  triple). UPDATEs on rows whose `vintage_date < today` are a bug.
- No two rows share `(series_id, reference_date, vintage_date)`.

If you see `vintage_date < reference_date` for a non-future
observation, or an UPDATE that touched a row whose `vintage_date` is
not `today`, that's a bug — flag it.

---

## Phase 5 — Check Idempotency

Run `python main.py` twice in a row against the same database. The second
run must produce:

- Zero new rows in `metadata` (and zero updates).
- Zero new rows in `time_series`.
- One new row in `logs` with `status='success'`.

If the second run writes data, the upsert logic is not idempotent — flag
it.

---

## Phase 6 — Report

Produce a short, structured audit report. Sections:

1. **Summary** — number of series audited, number of issues found, severity
   breakdown.
2. **Findings** — one bullet per issue:
   - `series_id` (or "structural")
   - What the collector says
   - What the source says
   - Severity: `blocker` (wrong values), `major` (wrong scope/unit),
     `minor` (wrong wording in description).
   - Suggested fix (which file, which line).
3. **Verified clean** — list of series that passed.

Do **not** silently fix anything during the audit. The audit reports;
fixes are a separate task the user authorizes after reading the report.

---

## What Counts as a Blocker

- A stored value disagrees with the source by more than rounding error.
- The wrong source ID is being used (e.g. we pull table 1737 but
  metadata says it's table 1736).
- A series labeled "monthly" that is actually quarterly (frequency must
  reflect what the source publishes, not what we want).
- A series whose `country` field is wrong.
- Vintage logic is broken (UPDATEs in place, missing initial vintages).

## What Counts as Minor

- Description wording differences that don't change meaning.
- Capitalization or punctuation.
- Slightly stale `last_observation` if the latest publication hasn't been
  pulled yet (this is normal between runs).

---

## When to Use vs Not

Use this skill when:

- The collector has been running for a while and the user wants confidence.
- A user reports a value that doesn't match the source.
- Before promoting a collector from staging to PROD.

Do not use this skill to:

- Add new series (use `series-selection` and `build-collector`).
- Restructure the repository (use `build-collector`).
- Investigate a single failed run (read `logs.log_text` instead).
