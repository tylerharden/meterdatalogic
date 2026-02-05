# meterdatalogic

meterdatalogic is a lightweight Python package that provides data transformation, validation, and analytics logic for customer interval meter data.  
It’s designed to serve as the core analytical engine for the Meter Data Tool (MDT) — usable from web apps, notebooks, or pipelines.

- Canonical Data Shape — normalise datasets to a consistent schema for reliable analytics.
- Small, Composable Modules — ingest, validate, transform, summary, pricing, scenario.
- Framework-Agnostic — works in Django, FastAPI, notebooks, or jobs.
- Plot-Ready Outputs — tidy DataFrames or JSON-ready dicts.
- Self-Validating — schema checks for tz-aware, sorted, duplicate-free data.
- Optimised for interval energy data — ToU, demand windows, tariff calculation.

---

## Install

### Using uv (recommended - much faster!)

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (uv automatically creates and manages .venv)
cd meterdatalogic
uv sync --all-extras

# Run commands without activating the venv!
uv run pytest
uv run ruff check .

# Or use make targets
make install  # = uv sync --all-extras
make test     # = uv run pytest -q
make lint     # = uv run ruff check .
```

### Using pip

```bash
# From this repo (editable install for development)
pip install -e ./meterdatalogic[dev]

# Or bring your own env with deps
pip install pandas numpy nemreader
```

> **Why uv?** 
> - 10-100x faster than pip (installation drops from ~60s to ~5s)
> - Automatically manages virtual environments (no activation needed!)
> - Better dependency resolution
> - Just use `uv run <command>` and it handles everything
> - See [uv documentation](https://docs.astral.sh/uv/) for more.

### Requirements

- **Python**: 3.10+
- **pandas**: >=2.0.0 (tested with 2.3.3)
  - pandas >=2.2 recommended for `include_groups` parameter support
  - Earlier versions will fall back to legacy behavior with a warning
- **numpy**: >=1.24.0
- **nemreader**: >=0.9.2 (optional, only needed for NEM12 file parsing)

### Timezone Handling

All timestamps in the canonical schema are **tz-aware**. The default timezone is `Australia/Brisbane` (no DST). 
You can specify any valid timezone during ingest:

```python
df = ml.ingest.from_dataframe(raw_df, tz="Australia/Sydney")  # DST-aware
```

Key principles:
- Input data with naive timestamps is localized to the specified timezone
- DST transitions are handled correctly (gaps and overlaps)
- All operations preserve timezone information
- Output timestamps remain tz-aware

---

## Documentation

Comprehensive documentation is available in the [docs/](docs/) folder:

- **[Getting Started](docs/guides/setup_environment.md)** - Installation and setup
- **[Examples & Use Cases](docs/guides/examples.md)** - Practical recipes
- **[API Reference](docs/reference/api-reference.md)** - Complete API documentation
- **[Feature Guides](docs/features/)** - Deep dives into insights, scenarios, validation
- **[Contributing](docs/guides/contributing.md)** - Developer guide

---

## Project Structure

```
meterdatalogic/
  __init__.py
  canon.py          # Canonical schema definitions
  types.py          # Type definitions (CanonFrame, Plan, etc.)
  exceptions.py     # CanonError exception
  utils.py          # Helper functions
  ingest.py         # Data loading (NEM12, CSV, DataFrame)
  validate.py       # Schema validation
  transform.py      # Aggregation, ToU binning
  summary.py        # JSON-ready summaries
  pricing.py        # Tariff calculations
  scenario.py       # Solar/battery/EV modeling
  formats.py        # Format conversion
  insights/         # Pattern detection & recommendations
    __init__.py
    engine.py       # Insight generation orchestration
    config.py       # Configuration and thresholds
    types.py        # Insight type definitions
    evaluators_*.py # Evaluator functions
tests/              # Test suite
docs/               # Documentation
```

### Module Overview

- **ingest** — Load NEM12, CSV, or DataFrame to canonical format
- **validate** — Enforce schema rules (tz-aware, sorted, unique timestamps)
- **transform** — Aggregate by time/ToU, calculate profiles and peaks
- **summary** — Generate JSON-ready summaries for dashboards
- **pricing** — Calculate billables and costs from tariff plans
- **scenario** — Model solar PV, battery storage, and EV charging
- **insights** — Automated pattern detection and recommendations
- **formats** — Convert between CanonFrame and JSON representations

---

## Canonical Schema

Every dataset processed conforms to the canonical schema:

- Index t_start: tz-aware DatetimeIndex, strictly increasing.
- Columns:
  - nmi: str (single site per frame).
  - channel: str (source register label, e.g., E1, B1).
  - flow: str (grid_import, controlled_load_import, grid_export_solar).
  - kwh: float (energy in the interval; import/export indicated by flow, not sign).
  - cadence_min: int (interval minutes, e.g., 30/15/5).

Conventions:
- Import (customer consumption) and export (PV feed-in) are separate flows.
- Default timezone is "Australia/Brisbane" unless specified.

---

## Quick Start

### 1) Ingest

Normalise raw data to canonical form.

```python
import meterdatalogic as ml

df = ml.ingest.from_dataframe(raw_df, tz="Australia/Brisbane")
ml.validate.assert_canon(df)  # raises CanonError on issues
```

### 2) Transform

Unified aggregation helpers.

```python
# Daily energy by flow (wide columns)
daily = ml.transform.aggregate(df, freq="1D", groupby="flow", pivot=True)

# Monthly peak demand (MF 16:00–21:00) in kW
demand = ml.transform.aggregate(
  df,
  freq="1MS",
  flows=["grid_import"],
  metric="kW",          # derive kW from kWh using cadence
  stat="max",           # max within each monthly bucket
  out_col="demand_kw",
  window_start="16:00",
  window_end="21:00",
  window_days="MF",     # ALL | MF (Mon–Fri) | MS (Mon–Sun?)
)

# Time-of-Use bins (month + one column per band name)
bands = [
  ml.types.ToUBand("off","00:00","16:00",22.0),
  ml.types.ToUBand("peak","16:00","21:00",45.0),
  ml.types.ToUBand("shoulder","21:00","24:00",28.0),
]
tou = ml.transform.tou_bins(df, bands)

# Average-day profile and top hours
prof = ml.transform.profile(df)  # columns: slot, flows..., import_total
top = ml.transform.top_n_from_profile(prof, n=4)
print(top["hours"])  # e.g., ['18','19','20','21']
```

### 3) Summary

JSON-ready summary payloads for dashboards.

```python
summary = ml.summary.summarise(df)
print(summary["meta"])     # start/end/cadence/days
print(summary["energy"])   # totals per flow
```

### 4) Pricing

Estimate monthly bills from interval data.

```python
plan = ml.types.Plan(
    usage_bands=[
        ml.types.ToUBand("off","00:00","16:00",22.0),
        ml.types.ToUBand("peak","16:00","21:00",45.0),
        ml.types.ToUBand("shoulder","21:00","24:00",28.0),
    ],
    demand=ml.types.DemandCharge("16:00","21:00","MF",12.0),
    fixed_c_per_day=95.0,
    feed_in_c_per_kwh=6.0,
)

bill = ml.pricing.compute_billables(df, plan, mode="monthly")
cost = ml.pricing.estimate_costs(bill, plan)
```

```python
cycles = [("2025-05-31", "2025-06-30"), ("2025-07-01", "2025-07-30")]
bill_cycles = ml.pricing.compute_billables(df, plan, mode="cycles", cycles=cycles)
bills = ml.pricing.estimate_costs(bill_cycles, plan, pay_on_time_discount=0.07, include_gst=True)
```

### 5) Scenarios (EV, PV, Battery)

Simulate EV charging, PV generation, and battery self-consumption, then optionally price the outcome.

```python
ev = ml.types.EVConfig(daily_kwh=8.0, max_kw=7.0, window_start="18:00", window_end="22:00", days="ALL", strategy="immediate")
pv = ml.types.PVConfig(system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15, seasonal_scale={"01":1.05,"06":0.9})
bat = ml.types.BatteryConfig(capacity_kwh=10.0, max_kw=5.0, round_trip_eff=0.9, soc_min=0.1, soc_max=0.95)

result = ml.scenario.run(df, ev=ev, pv=pv, battery=bat, plan=plan)
```

---

## Performance Notes

- **Typical processing**: 1M intervals (1 year of 30-min data) in ~2-3 seconds on modern hardware
- **Memory usage**: ~150-200 bytes per interval row (5-interval DataFrame overhead)
- **Recommended limits**: Up to 10M intervals (10 years of data) works well in-memory
- **Optimization tips**:
  - Filter to single NMI before processing when working with multi-site data
  - Use `freq` parameter in `aggregate()` to downsample before heavy computation
  - Profile-based summaries (`profile()`, `top_n_from_profile()`) are pre-aggregated for speed

---

## Testing

```bash
# Run all tests
uv run pytest
# or
make test

# Run with coverage
uv run pytest --cov=meterdatalogic

# Run specific test file
uv run pytest tests/test_transform.py
```

---

## Development

```bash
# Lint code
make lint
# or
uv run ruff check .

# Format code
uv run ruff format .

# Run pre-commit hooks
uv run pre-commit run --all-files
```

See [Contributing Guide](docs/guides/contributing.md) for detailed development workflow.

---

## Releasing

Releases are automated via GitHub Actions with PyPI trusted publishing.

### Quick Release

```bash
# 1. Bump version
make bump-patch   # 0.1.4 → 0.1.5
make bump-minor   # 0.1.4 → 0.2.0
make bump-major   # 0.1.4 → 1.0.0

# 2. Push to GitHub
git push && git push --tags
```

### What Happens Automatically

When you push a tag (e.g., `v0.1.5`):

1. ✅ GitHub Actions builds the package (wheel + sdist)
2. ✅ **Publishes to PyPI** using trusted publishing (no token needed!)
3. ✅ Creates GitHub Release with artifacts
4. ✅ Detects pre-releases (alpha, beta, rc) automatically

### Pre-releases

Support for alpha, beta, and release candidates:

```bash
# Update version in pyproject.toml
version = "0.1.5-alpha"

# Tag and push
git tag v0.1.5-alpha
git push --tags
```

Pre-releases are marked as such on both GitHub and PyPI. Users can install with:
```bash
pip install --pre meterdatalogic
```

### PyPI Setup (One-time)

For automated publishing, configure PyPI trusted publishing:

1. Go to https://pypi.org/manage/account/publishing/
2. Add a new publisher:
   - **PyPI project name**: `meterdatalogic`
   - **Owner**: `tylerharden`
   - **Repository**: `meterdatalogic`
   - **Workflow**: `release.yml`
   - **Environment**: (leave blank)

No API tokens needed! See [Release Workflow docs](docs/releasing-workflow.md) for details.

---

## Installation from PyPI

Once published:

```bash
# Install latest stable version
pip install meterdatalogic

# Install with optional dependencies
pip install meterdatalogic[dev]  # Development tools
pip install meterdatalogic[nem12]  # NEM12 support

# Install pre-release versions
pip install --pre meterdatalogic
```