# collector_ofgem_uk

Standalone collector for Ofgem's official Energy Price Cap final levelised cap-rates workbook. It stores raw published cap outputs by fuel, region and payment method plus GB-average electricity cost components. The current source smoke yields 352 series and 2,264 observations from 2017-Q2 through 2026-Q4.

Ofgem announces a cap before it takes effect. `reference_date` is the effective period start; current-workbook history without an archived announcement timestamp is conservatively `first_seen`, never backdated. The artifact snapshot preserves the published period detail.

## Install and run (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
Copy-Item .env.example .env
pytest -q
python main.py
```

Set `COLLECTOR_DB_URL` to PostgreSQL and allow `ofgem.gov.uk`. Databricks is optional: install `.[databricks]`, set `PROD=true`, and configure the documented DBX/AKV variables. No sibling collector is required.

Source smoke: `python -c "from scripts.extract import collect; x=collect(); print(len(x.catalog), len(x.observations))"`.

See [METHODOLOGY.md](METHODOLOGY.md) and [POINT_IN_TIME.md](POINT_IN_TIME.md).
