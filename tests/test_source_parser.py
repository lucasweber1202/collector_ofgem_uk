from datetime import UTC, datetime
from zipfile import BadZipFile

import pytest

from scripts.extract import parse_xlsx


def test_parser_fails_closed_on_invalid_workbook() -> None:
    with pytest.raises(BadZipFile):
        parse_xlsx(b"not an xlsx", "snapshot", "https://ofgem.gov.uk", datetime.now(UTC))
