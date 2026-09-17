"""Ofgem default-tariff cap levels and published cost components."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin

import httpx
import openpyxl

from scripts.config import MAX_DOWNLOAD_BYTES, REQUEST_TIMEOUT, USER_AGENT
from scripts.snapshots import Snapshot, build_snapshot
from scripts.time_series import Observation

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
