"""Ofgem default-tariff cap levels and published cost components."""

from __future__ import annotations

import hashlib
import io
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin

import httpx
import openpyxl

from scripts.config import (
    MAX_DOWNLOAD_BYTES,
    MAX_STALE_MONTHS,
    MIN_HISTORY_YEARS,
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from scripts.snapshots import Snapshot, build_snapshot
from scripts.time_series import Observation

logger = logging.getLogger(__name__)


# -- series_id contract (GUIDELINES.md 4) ---------------------------------
# series_id is uppercase, underscore-separated and ordered coarse -> fine. The
# pair below is the canonical public surface: parse splits an id into its
# components, build rejoins them, and build(*parse(sid)) == sid for every id
# this collector emits. Only economic identity is encoded -- never a delivery
# provider or any other detail of how the value reached us.


def parse_series_id(series_id: str) -> tuple[str, ...]:
    """Split a series_id into its underscore-delimited components.

    Raises ValueError on anything this collector would not have produced:
    lowercase, empty components, or an id with no structure at all.
    """
    if not series_id or series_id != series_id.upper():
        raise ValueError(f"series_id must be uppercase: {series_id!r}")
    components = tuple(series_id.split("_"))
    if any(not component for component in components):
        raise ValueError(f"series_id has an empty component: {series_id!r}")
    return components


def build_series_id(*components: str) -> str:
    """Rejoin the tuple parse_series_id returned into the original id."""
    if not components:
        raise ValueError("series_id needs at least one component")
    if any(not component or component != component.upper() for component in components):
        raise ValueError(f"invalid series_id components: {components!r}")
    return "_".join(components)


# -- 5.1 usable-series filtering ------------------------------------------


@dataclass(frozen=True)
class UsabilityReport:
    """What the filter removed, for logging and for tests to assert on."""

    kept: tuple[str, ...]
    stale: tuple[str, ...]
    short_history: tuple[str, ...]
    empty: tuple[str, ...]

    @property
    def dropped(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.stale) | set(self.short_history) | set(self.empty)))


def _months_between(earlier: date, later: date) -> int:
    """Whole months from ``earlier`` to ``later``, day-of-month aware."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


def _is_valid(value: Any) -> bool:
    """A real observation: present, numeric and finite."""
    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric)


def assess_series(
    reference_dates: list[date],
    today: date,
    max_stale_months: int = MAX_STALE_MONTHS,
    min_history_years: float = MIN_HISTORY_YEARS,
) -> str:
    """Classify one series from the reference dates of its valid observations.

    Returns ``"keep"``, ``"empty"``, ``"stale"`` or ``"short_history"``.
    Recency is judged at the period end and over non-null values only: a source
    that keeps listing a discontinued series with empty recent cells must not
    look live because of those blanks.
    """
    if not reference_dates:
        return "empty"
    first, last = min(reference_dates), max(reference_dates)
    if _months_between(last, today) > max_stale_months:
        return "stale"
    if _months_between(first, last) < round(min_history_years * 12):
        return "short_history"
    return "keep"


def filter_usable_series(
    observations: list[Any],
    catalog: dict[str, dict[str, Any]],
    today: date,
    max_stale_months: int = MAX_STALE_MONTHS,
    min_history_years: float = MIN_HISTORY_YEARS,
) -> tuple[list[Any], dict[str, dict[str, Any]], UsabilityReport]:
    """Drop obsolete and history-less series before anything is persisted.

    Runs after parsing and before the time_series / metadata upsert, so the
    standardized tables never carry a dead or stub series, and prunes the
    catalog alongside the observations so metadata can never describe a series
    the database does not hold (GUIDELINES.md 5.1).
    """
    valid_dates: dict[str, list[date]] = {}
    for observation in observations:
        if _is_valid(observation.value):
            valid_dates.setdefault(observation.series_id, []).append(observation.reference_date)

    verdicts: dict[str, str] = {}
    for series_id in set(catalog) | {o.series_id for o in observations}:
        verdicts[series_id] = assess_series(
            valid_dates.get(series_id, []), today, max_stale_months, min_history_years
        )

    keep = {series_id for series_id, verdict in verdicts.items() if verdict == "keep"}
    report = UsabilityReport(
        kept=tuple(sorted(keep)),
        stale=tuple(sorted(s for s, v in verdicts.items() if v == "stale")),
        short_history=tuple(sorted(s for s, v in verdicts.items() if v == "short_history")),
        empty=tuple(sorted(s for s, v in verdicts.items() if v == "empty")),
    )

    if report.dropped:
        logger.info(
            "Usable-series filter: kept %d, dropped %d "
            "(stale=%d short_history=%d empty=%d; max_stale_months=%d min_history_years=%s)",
            len(report.kept),
            len(report.dropped),
            len(report.stale),
            len(report.short_history),
            len(report.empty),
            max_stale_months,
            min_history_years,
        )
        for series_id in report.stale:
            logger.info(
                "Dropped %s: last valid observation older than %d months",
                series_id,
                max_stale_months,
            )
        for series_id in report.short_history:
            logger.info(
                "Dropped %s: valid history shorter than %s years", series_id, min_history_years
            )
        for series_id in report.empty:
            logger.info("Dropped %s: no valid observations", series_id)
    else:
        logger.info("Usable-series filter: all %d series usable", len(report.kept))

    kept_observations = [o for o in observations if o.series_id in keep]
    kept_catalog = {sid: fields for sid, fields in catalog.items() if sid in keep}
    return kept_observations, kept_catalog, report


LANDING = "https://www.ofgem.gov.uk/energy-regulation/domestic-and-non-domestic/energy-pricing-rules/energy-price-cap/energy-price-cap-default-tariff-levels"
COMPONENTS = {
    "DF",
    "CM",
    "AA",
    "PC",
    "NC",
    "OC",
    "SMNCC",
    "IC",
    "PAAC",
    "PAP",
    "CO",
    "DRC",
    "EBIT",
    "HAP",
    "Levelisation",
    "Total_GB average",
    "Total inc VAT",
}


@dataclass(frozen=True)
class ExtractedData:
    observations: list[Observation]
    snapshots: list[Snapshot]
    catalog: dict[str, dict[str, Any]]
    releases: list[datetime]
    availability_by_key: dict[tuple[str, date], tuple[datetime, str, date | None]]
    min_lag_days: int = 0
    max_lag_days: int = 0
    inferred_lag_days: int | None = None


def _slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _period(value: str) -> tuple[date, date]:
    months = {
        name: month
        for month, names in enumerate(
            (
                ("Jan", "January"),
                ("Feb", "February"),
                ("Mar", "March"),
                ("Apr", "April"),
                ("May",),
                ("Jun", "June"),
                ("Jul", "July"),
                ("Aug", "August"),
                ("Sep", "Sept", "September"),
                ("Oct", "October"),
                ("Nov", "November"),
                ("Dec", "December"),
            ),
            1,
        )
        for name in names
    }
    match = re.fullmatch(r"([A-Z][a-z]+) (\d{4}) - ([A-Z][a-z]+) (\d{4})", value.strip())
    if not match:
        raise ValueError(f"Unrecognised Ofgem cap period {value!r}")
    start = date(int(match.group(2)), months[match.group(1)], 1)
    end_month = months[match.group(3)]
    end = date(int(match.group(4)) + (end_month == 12), end_month % 12 + 1, 1)
    return start, end


def parse_xlsx(
    body: bytes, snapshot_id: str, source_url: str, collected: datetime
) -> tuple[
    list[Observation],
    dict[str, dict[str, Any]],
    dict[tuple[str, date], tuple[datetime, str, date | None]],
]:
    book = openpyxl.load_workbook(io.BytesIO(body), data_only=True, read_only=False)
    required = {"1a Levelised DTC", "1b Historical level tables"}
    if not required.issubset(book.sheetnames):
        raise ValueError(f"Ofgem workbook sheet drift: {book.sheetnames}")
    observations: list[Observation] = []
    catalog: dict[str, dict[str, Any]] = {}
    availability: dict[tuple[str, date], tuple[datetime, str, date | None]] = {}
    keys: set[tuple[str, date]] = set()
    historical = book["1b Historical level tables"]
    payment = "OTHER"
    consumption = "UNKNOWN"
    for row in range(1, historical.max_row + 1):
        label = str(historical.cell(row, 2).value or "").strip()
        if label in {"Other Payment Method", "Standard Credit", "PPM"}:
            payment = _slug(label)
        if label in {"Nil consumption", "Typical consumption"}:
            consumption = _slug(label)
        normalized = label.rstrip()
        if normalized not in COMPONENTS:
            continue
        header_row = row
        while header_row > 1 and not any(
            re.match(r"[A-Z][a-z]{2}", str(historical.cell(header_row, c).value or ""))
            for c in range(3, 32)
        ):
            header_row -= 1
        series_id = f"OFGEM_ELEC_SINGLE_{payment}_{consumption}_{_slug(normalized)}"
        catalog[series_id] = {
            "source_id": "ofgem_price_cap",
            "name": f"Electricity single-rate {payment} {consumption} {normalized}",
            "description": "Raw GB-average default-tariff-cap component in pounds per customer per year. reference_date is effective_start; workbook retains the period end.",
            "frequency": "quarterly",
            "unit": "currency",
            "eco_group": "inflation",
            "source_url": source_url,
            "last_publish_date": collected.date(),
        }
        for col in range(3, 32):
            period_label = historical.cell(header_row, col).value
            raw = historical.cell(row, col).value
            if not isinstance(period_label, str) or not isinstance(raw, (int, float)):
                continue
            start, _end = _period(period_label)
            key = (series_id, start)
            if key in keys:
                raise ValueError(f"Duplicate Ofgem key {key}")
            keys.add(key)
            observations.append(Observation(series_id, start, float(raw), snapshot_id))
            availability[key] = (collected, "first_seen", None)
    current = book["1a Levelised DTC"]
    period_text = str(current.cell(6, 3).value)
    current_start, _current_end = _period(period_text)
    for payment, first_row in (("OTHER", 14), ("STANDARD_CREDIT", 35), ("PPM", 56)):
        codes = [str(current.cell(first_row - 3, c).value or "") for c in range(3, 9)]
        if len([c for c in codes if c]) != 6:
            raise ValueError("Ofgem current output columns drifted")
        for row in range(first_row, first_row + 15):
            region = str(current.cell(row, 2).value or "")
            if not region or region.startswith("GB average"):
                continue
            for col, code in zip(range(3, 9), codes):
                raw = current.cell(row, col).value
                if not isinstance(raw, (int, float)):
                    raise TypeError(f"Missing Ofgem current value {payment}/{region}/{code}")
                series_id = f"OFGEM_CAP_{payment}_{_slug(region)}_{_slug(code)}"
                key = (series_id, current_start)
                if key in keys:
                    raise ValueError(f"Duplicate Ofgem key {key}")
                keys.add(key)
                observations.append(Observation(series_id, current_start, float(raw), snapshot_id))
                availability[key] = (collected, "first_seen", None)
                catalog[series_id] = {
                    "source_id": "ofgem_price_cap",
                    "name": f"{region} {code}",
                    "description": f"Raw Ofgem levelised cap output, effective {period_text}; announced before effective_start.",
                    "frequency": "quarterly",
                    "unit": "currency",
                    "eco_group": "inflation",
                    "source_url": source_url,
                    "last_publish_date": collected.date(),
                }
    if len(observations) < 500 or len(catalog) < 150:
        raise ValueError("Ofgem workbook unexpectedly lost history or dimensions")
    return observations, catalog, availability


def collect() -> ExtractedData:
    fetched = datetime.now(UTC)
    with httpx.Client(
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        page = client.get(LANDING)
        page.raise_for_status()
        matches = re.findall(
            r'href=["\']([^"\']+\.xlsx)["\'][^>]*>.*?Final levelised cap rates model',
            page.text,
            re.IGNORECASE | re.DOTALL,
        )
        if not matches:
            raise ValueError("No Ofgem Annex 9 workbook discovered")
        url = urljoin(LANDING, matches[0])
        response = client.get(url)
        response.raise_for_status()
    body = response.content
    if not body or len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"Invalid Ofgem artifact size {len(body)}")
    digest = hashlib.sha256(body).hexdigest()
    observations, catalog, availability = parse_xlsx(body, digest, url, fetched)
    snapshot = build_snapshot(
        "ofgem_price_cap",
        url,
        "ofgem_annex_9.xlsx",
        body,
        digest,
        response.headers.get("etag"),
        response.headers.get("last-modified"),
        fetched,
        fetched.date(),
    )
    return ExtractedData(observations, [snapshot], catalog, [], availability)
