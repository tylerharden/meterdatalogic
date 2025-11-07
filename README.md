# meterdatalogic

**meterdatalogic** is a lightweight Python package that provides **data transformation, validation, and analytics logic** for customer interval meter data.  
It’s designed to serve as the core analytical engine for the *Meter Data Tool* (MDT) proof-of-concept — a Django-based web application deployed on AWS.

> The package provides consistent data structures and reusable functions for resampling, summarising, and analysing electricity interval data, regardless of where the data originated (e.g., NEM12 file, API upload, or internal system).

---

## Key Features

- **Canonical Data Shape** — all datasets are normalised to a consistent format for processing and analytics.
- **Small, Composable Modules** — single-responsibility files for ingest, validation, transformation, summarisation, and pricing.
- **Framework-Agnostic** — usable in Django, FastAPI, notebooks, or serverless pipelines.
- **Plot-Ready Outputs** — functions return tidy DataFrames or JSON-ready dictionaries for visualisation.
- **Self-Validating** — built-in schema checks to ensure clean, tz-aware, sorted data.
- **Optimised for Interval Energy Data** — handles common energy data use-cases like ToU, demand, and tariff analysis.

---

## Project Structure

```
meterdatalogic/
  __init__.py
  canon.py
  types.py
  utils.py
  ingest.py
  validate.py
  transform.py
  summary.py
  pricing.py
tests/
  ...
examples/
  notebook_examples.ipynb
```

### Module Overview

| File | Purpose |
|------|----------|
| **`canon.py`** | Defines the *canonical schema* for all meter data processed by the package. Contains constants such as index name, default timezone, cadence, and channel mappings (`E1 → grid_import`, `B1 → grid_export_solar`). |
| **`types.py`** | Centralised data types using `TypedDict` and `dataclass` for strong typing. Includes structures for summaries, ToU bands, demand windows, and tariff plans. |
| **`utils.py`** | Helper functions used throughout the package — timezone localisation, cadence inference, date range helpers, and frequency conversions. |
| **`ingest.py`** | Entry point for loading and normalising data. Provides `from_dataframe()` and `from_nem12()` to read raw interval data from various sources and convert it into canonical form. |
| **`validate.py`** | Data quality checks and guards. Ensures index is tz-aware, sorted, and free from negative or duplicate values. Provides lightweight integrity enforcement before analytics. |
| **`transform.py`** | Core transformation logic. Includes resampling, day/month aggregations, 24-hour average profiles, Time-of-Use (ToU) binning, and demand window analysis. |
| **`summary.py`** | Generates compact, JSON-ready summary payloads for dashboards. Produces total energy, average daily usage, 24-hour profile, peaks, and monthly rollups. |
| **`pricing.py`** | Lightweight tariff calculation utilities. Converts kWh data into cost estimates based on ToU bands, demand charges, fixed supply charges, and feed-in credits. |
| **`tests/`** | End-to-end pytest suite verifying canonicalisation, validation, ToU, pricing, and summary functions. |
| **`examples/`** | Jupyter Notebook with Plotly visualisations for daily, monthly, and ToU analyses. |

---

## Data Model

Every dataset processed by `meterdatalogic` conforms to the **canonical schema**:

| Column | Type | Description |
|---------|------|-------------|
| `t_start` | `DatetimeIndex (tz-aware)` | Start time of the interval. Index of the DataFrame. |
| `nmi` | `str` | National Meter Identifier (unique per site). |
| `channel` | `str` | Raw register suffix from the data source (e.g., `E1`, `B1`). |
| `flow` | `str` | Semantic energy flow (`grid_import`, `grid_export_solar`, etc.). |
| `kwh` | `float` | Energy used during the interval (always positive). |
| `cadence_min` | `int` | Interval length in minutes (typically 30, 15, or 5). |

### Conventions
- **Import** (customer consumption) is *positive* kWh.
- **Export** (PV feed-in) is represented by a *flow label*, not by negative sign.
- **Index** (`t_start`) must be tz-aware and strictly monotonic.
- **Default timezone** is `"Australia/Brisbane"` unless otherwise specified.

---

## Core Features

### 1. Ingestion
Normalize data from any source to the canonical structure.

```python
import meterdatalogic as ml

df = ml.ingest.from_dataframe(raw_df, tz="Australia/Brisbane")
# or from a NEM12 file
df = ml.ingest.from_nem12("data/nmi_data.csv", tz="Australia/Brisbane")
```

### 2. Validation
Ensure data quality before use.

```python
ml.validate.assert_canon(df)
# raises CanonError if tz missing, index unsorted, or columns missing
```

### 3. Transformation
Resample, aggregate, and slice data easily.

```python
daily   = ml.transform.groupby_day(df)
monthly = ml.transform.groupby_month(df)
profile = ml.transform.profile24(df)
tou     = ml.transform.tou_bins(df, bands)
demand  = ml.transform.demand_window(df)
```

### 4. Summary & Insights
Generate JSON-ready summary payloads for dashboards.

```python
summary = ml.summary.summarise(df)
print(summary["meta"])
print(summary["energy"])
```

### 5. Pricing
Estimate bills from interval data.

```python
plan = ml.types.Plan(
    usage_bands=[
        ml.types.ToUBand("off","00:00","16:00",22.0),
        ml.types.ToUBand("peak","16:00","21:00",45.0),
        ml.types.ToUBand("shoulder","21:00","24:00",28.0),
    ],
    demand=ml.types.DemandCharge("16:00","21:00","MF",12.0),
    fixed_c_per_day=95.0,
    feed_in_c_per_kwh=6.0
)

# Simple monthly billing
cost = ml.pricing.estimate_monthly_cost(df, plan)

# Complex cycles mode
cycles = [
    ("2025-05-31", "2025-06-30"),
    ("2025-07-01", "2025-07-30"),
]
bills = ml.pricing.estimate_cycle_costs(
    df, plan, cycles,
    pay_on_time_discount=0.07,   
    include_gst=True            
)
```
