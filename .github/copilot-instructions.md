# Predictor Collector Guidelines — United Kingdom

This document complements the macro collector fleet guidelines for repositories whose purpose is collecting explanatory predictors for UK inflation forecasts.

## 1. Scope

A predictor collector gathers one publisher/source family. It does not collect the ONS CPI target, rebuild CPI weights, create a synthetic CPI or run forecast models.

Naming: `collector_<source>_uk`. Repository name and database schema must match exactly.

Examples: `collector_desnz_uk`, `collector_defra_uk`, `collector_ofgem_uk`, `collector_hmrc_uk`, `collector_elexon_uk`.

## 2. Standard repository shape

```
collector_<source>_uk/
├── .env.example
├── .gitignore
├── README.md
├── METHODOLOGY.md
├── POINT_IN_TIME.md
├── main.py
├── pyproject.toml
├── requirements.txt
├── scripts/
│   ├── __init__.py
│   ├── availability.py
│   ├── config.py
│   ├── databricks_engine.py
│   ├── db.py
│   ├── extract.py
│   ├── init_db.py
│   ├── metadata.py
│   ├── run_logs.py
│   ├── snapshots.py
│   └── time_series.py
└── tests/
```

A source may add flat helper modules when the upstream source genuinely forces them. Do not create subpackages, `core/`, `lib/`, `common/`, a base class or plugin system.

## 3. Standard tables

### metadata
One row per series. Required fields include `series_id`, `source_id`, name, description, `country=GBP`, frequency, unit, first/last observation, observation count, `eco_group`, source URL, last publish date and collected timestamp.

### time_series
Raw source values only, keyed by `(series_id, reference_date, vintage_date)`. Never store modelling transformations such as MoM, YoY, monthly averages or MTD when the raw level exists.

### availability
One row per stored vintage, carrying `release_date`, `available_at`, `availability_basis`, `source_snapshot_id` and collected timestamp. This table is mandatory for predictor collectors.

### source_snapshots
One row per distinct parsed raw artifact, keyed by SHA-256, with source URL, source publication date if available, ETag, Last-Modified, byte size and raw path.

### logs
One success/error row per execution, including traceback on failure.

## 4. Point-in-time rules

`reference_date`, `release_date`, `available_at`, `vintage_date` and `collected_at` are distinct concepts.

Allowed availability bases: `official_timestamp`, `official_date`, `archived_release`, `first_seen`, `inferred`, `unknown`.

`get_series_as_of()` excludes `inferred` and `unknown` by default.

Historical revisions must never inherit the original release timestamp. If no explicit revision release timestamp is available, a newly discovered historical revision uses `available_at=collected_at`, `availability_basis=first_seen`, `release_date=NULL`.

Because the fleet key stores `vintage_date` as a DATE, a changed value observed twice on the same UTC date must fail closed rather than overwrite an existing same-day vintage. This conservative rule prevents intraday look-ahead.

## 5. Idempotency

Fresh DB: full available history is collected.

Unchanged second run: no new rows in `time_series`, `availability`, `source_snapshots` or unchanged `metadata`; only the run log changes.

Changed historical value on a later day: insert a new vintage and keep the earlier vintage.

## 6. Source validation

Every extractor validates before persistence. At minimum: expected source schema, no duplicate `(series_id, reference_date)` keys, valid units, non-empty output, defensible cadence/frequency, finite/plausible values, and expected first/latest boundaries where the source supports such assertions.

Do not silently accept a renamed/missing required column. Fail and re-audit the source.

## 7. Historical coverage

Use the maximum defensible historical depth available from the source. If machine-readable current data begins later than an official historical workbook, stitch the two sources with an explicit overlap/deduplication rule rather than discarding older history.

Never fabricate historical `available_at`. Historical periods without evidence are marked `inferred` or `unknown`.

## 8. Relationship to uk_inflation_predictors

Source collectors own extraction and storage only. `uk_inflation_predictors` becomes the research layer and owns predictor-to-ONS target mapping, transformations, correlations, lead/lag tests, AR benchmarks, rolling/expanding pseudo-out-of-sample evaluation and predictor ranking.

No predictor collector imports `uk_inflation_predictors`, `collector_ons_cpi`, another predictor collector, or a shared package.

## 9. Definition of done for a new source

A source is ready only when: fresh historical build succeeds; latest values match the upstream source; an unchanged rerun is a data no-op; later-day revisions preserve old vintages; same-day changes fail closed; snapshots are traceable; `get_series_as_of()` does not leak future information; source limitations are documented; and local tests pass.

