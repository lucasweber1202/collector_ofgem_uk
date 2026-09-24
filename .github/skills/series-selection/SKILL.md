---
name: series-selection
description: >
  Use this skill when deciding which series a collector should pull from a
  source. Codifies the rules for frequency, transformation preference, and
  geographic scope so the standardized `metadata` and `time_series` tables
  stay clean and consistent across collectors.
---

# Series Selection — Curation Guidelines

These rules apply whenever an agent decides what series to include in a
collector — at creation time, or when expanding an existing collector's
coverage. They keep the catalog focused, raw, and useful for downstream
ML / aggregation pipelines.

---

## 1. Frequency Gate

Only include series whose **native publication frequency matches the
collector's intended use**.

- If the collector is meant for monthly modelling: include monthly,
  biweekly, weekly, or daily series only. Exclude quarterly and annual,
  even when they are the "headline" version of the indicator.
- If a quarterly aggregate and a monthly proxy describe the same concept,
  pick the monthly proxy (e.g. choose IGAE over quarterly GDP).
- Stored `frequency` in `metadata` must reflect what the **source
  publishes**, not what we want it to be.

If the user has not specified an intended frequency, ask before deciding.

---

## 2. Prefer the Rawest Representation

When the same underlying variable is available in multiple forms, prefer
the form closest to the raw source. Downstream pipelines can derive
transformations themselves; they cannot un-transform.

| Preference rank | Form                                                  |
| --------------- | ----------------------------------------------------- |
| 1               | Raw level / index (e.g. CPI index, employment count)  |
| 2               | Seasonally-adjusted level                             |
| 3               | MoM / QoQ change                                      |
| 4               | YoY change                                            |
| 5               | Cumulative / YTD                                      |

Concretely:

- If the source publishes both the price index and the YoY inflation
  rate, store the index.
- If both raw and seasonally-adjusted versions exist, store the raw one.
  Add the SA version only if it carries information the raw version
  cannot reproduce client-side.
- Already-stored transformed series may stay for backwards compatibility,
  but **new additions follow this ranking**.

---

## 3. Geographic Scope

- National-level series first. Sub-national (state, city, metropolitan)
  series only when the user has explicitly asked.
- For cross-country comparisons, prefer series whose definition is
  internationally standardized (CPI, REER, IP indices).
- The `country` field in `metadata` should match the geographic scope of
  the series, not the agency that publishes it.

---

## 4. Series ID Convention

Every `series_id` is a structured, parseable, uppercase string. The
specific components are collector-specific (see the pilot's
`{TYPE}_{STAT}_{HORIZON}` example), but always:

- Uppercase.
- Components joined with `_`, ordered coarse → fine.
- Round-trippable: `extract.py` exports a `parse_series_id()` helper that
  returns a tuple of decoded fields, and `metadata.py`'s
  `_series_descriptive_row()` uses that decomposition to build the
  human-readable `name`, `description`, and `unit`.

Do **not**:

- Use the source's native ID directly as `series_id` if it is opaque.
  Wrap it in a structured ID and keep the native ID inside `extract.py`'s
  parameter mapping.
- Hand-write per-series names in a hardcoded dict. Derive them.

---

## 5. Decision Checklist

Before adding a new series to a collector, confirm each item:

- [ ] The native publication frequency matches the collector's intent.
- [ ] No coarser-grained alternative for the same concept was rejected
      in favor of a finer one.
- [ ] The chosen form is the rawest available (per §2).
- [ ] The geographic scope is national (or explicitly justified
      otherwise).
- [ ] The `series_id` follows §4 and is unique within the collector.
- [ ] `_series_descriptive_row()` produces a sensible `name`,
      `description`, and `unit` from this ID — no hand-written fallback.
- [ ] One sample observation has been verified against the source page
      to confirm the ID actually returns data.

---

## 6. When to Reject a Source-Suggested Series

Push back on the user (or on yourself) if:

- The series is published only as a YoY change and you have a level
  alternative.
- The series is quarterly and you have a monthly proxy.
- The series duplicates one already in the collector under a different
  source ID.
- The series is sub-national without a clear analytical reason.
- The series's `series_id` would not be uniquely decodable (component
  collision with another already-included series).
