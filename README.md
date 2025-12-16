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

```bash
# From this repo (editable install for development)
pip install -e ./meterdatalogic[dev]

# Or bring your own env with deps
pip install pandas numpy nemreader
```

Supported: Python 3.10+ and recent pandas versions. `nemreader` is only required for NEM12 ingest.

---

## Project Structure

```
meterdatalogic/
  __init__.py
  canon.py
  types.py
  exceptions.py
  utils.py
  ingest.py
  validate.py
  transform.py
  summary.py
  pricing.py
  scenario.py
tests/
  ...
```

### Module Overview

- canon.py — Canonical schema constants (index name, default TZ/cadence, channel→flow mappings).
- types.py — TypedDict/dataclass types (ToU bands, DemandCharge, Plan, EV/PV/Battery configs).
- exceptions.py — Domain-specific error classes (CanonError, TransformError, PricingError, ScenarioError, etc.) and require().
- utils.py — General helpers (month_label, build_canon_frame).
- ingest.py — Normalise raw data to canonical shape (from_dataframe, from_nem12).
- validate.py — Enforce canonical invariants (assert_canon, ensure).
- transform.py — Unified `aggregate(...)` for resampling/grouping and `tou_bins(...)` for ToU; helpers `profile(...)`, `period_breakdown(...)`, `base_from_profile(...)`, `window_stats_from_profile(...)`, `peak_from_profile(...)`, `top_n_from_profile(...)`.
- summary.py — JSON-ready payloads (energy totals, per-day avg, peaks, profile24, months).
- pricing.py — Unified billing API: `compute_billables(..., mode='monthly'|'cycles')` and `estimate_costs(...)`.
- scenario.py — EV/PV/Battery simulation and orchestration (run).
- insights/ — Config-driven insights & recommendations API (`generate_insights`) using canonical data, pricing, and scenarios.

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

## Testing

```bash
pytest -q
```

---

## Releasing (GitHub Actions)

We use semantic version tags vX.Y.Z and a release workflow that builds artifacts.

Steps:
1) Bump the version in pyproject.toml ([project.version]).
2) Create a Git tag vX.Y.Z and push, or run the “Release meterdatalogic” workflow with an input version.
3) The workflow builds wheel and sdist (dist/*.whl, *.tar.gz) and publishes a GitHub Release with assets.

Notes:
- Ensure pyproject version matches the tag. The workflow validates this.
- If you target AWS Lambda layers or Linux/aarch64, build wheels in a compatible environment (e.g., AWS SAM python3.12 aarch64 image) before publishing a layer.