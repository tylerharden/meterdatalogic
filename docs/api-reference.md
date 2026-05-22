# API Reference

Complete reference for all public modules in meterdatalogic.

> All DataFrames are `polars.DataFrame`. There is no pandas dependency.

---

## Import Pattern

```python
import meterdatalogic as ml

df = ml.ingest.from_nem12("data.csv")
ml.validate.assert_canon(df)

daily = ml.transform.aggregate(df, freq="1d", groupby="flow", pivot=True)
summary = ml.summary.summarise(df)
billables = ml.pricing.compute_billables(df, plan)
insights = ml.insights.generate_insights(df)
```

---

## Canonical Schema

`CanonFrame` is a `polars.DataFrame` with the following columns:

| Column | Type | Description |
|---|---|---|
| `t_start` | `Datetime(tz-aware)` | Interval start timestamp — tz-aware, sorted ascending |
| `nmi` | `String` | National Metering Identifier |
| `channel` | `String` | Source register label (e.g. `E1`, `B1`) |
| `flow` | `String` | `grid_import`, `controlled_load_import`, or `grid_export_solar` |
| `kwh` | `Float64` | Energy in the interval (always non-negative) |
| `cadence_min` | `Int32` | Interval length in minutes (e.g. 30, 15) |

`t_start` is a **regular column**, not an index.

---

## `canon`

Schema constants.

```python
ml.canon.INDEX_NAME      # "t_start"
ml.canon.REQUIRED_COLS   # ["nmi", "channel", "flow", "kwh", "cadence_min"]
ml.canon.CHANNEL_MAP     # {"E1": "grid_import", "E2": "controlled_load_import", "B1": "grid_export_solar"}
ml.canon.CANON_SCHEMA    # polars schema dict
```

---

## `ingest`

Load raw data into canonical form.

### `from_nem12(file_like, *, tz, channel_map, nmi)`

Parse a NEM12 file via nemreader 1.0.0.

```python
df = ml.ingest.from_nem12(
    "data/sample.csv",
    tz="Australia/Brisbane",   # default
    nmi=None,                  # filter to specific NMI (optional)
)
```

**Parameters:**
- `file_like` — file path (str) or file-like object
- `tz` (str) — timezone for tz-naive timestamps. Default: `"Australia/Brisbane"`
- `channel_map` (dict, optional) — override channel→flow mapping
- `nmi` (str, optional) — filter to a single NMI; raises if not found

**Returns:** `CanonFrame`

---

### `from_dataframe(df, *, tz, channel_map, nmi)`

Normalise a raw `polars.DataFrame` to canonical form.

```python
import polars as pl

raw = pl.read_csv("data/export.csv", try_parse_dates=True)
df = ml.ingest.from_dataframe(
    raw,
    tz="Australia/Sydney",
    nmi="NMI1234567",
)
```

**Parameters:**
- `df` (pl.DataFrame) — must have a timestamp column and a `kwh` (or aliased energy) column
- `tz` (str) — timezone for tz-naive timestamps
- `channel_map` (dict, optional) — override channel→flow mapping
- `nmi` (str, optional) — filter to a single NMI

Timestamp column is auto-detected from: `t_start`, `timestamp`, `time`, `ts`, `datetime`, `date`.
Energy column is auto-detected from: `kwh`, `energy`, `value`, `consumption`.

**Returns:** `CanonFrame`

---

## `validate`

### `assert_canon(df)`

Validate that a DataFrame conforms to canonical schema. Raises `CanonError` on violations.

**Checks:**
- `t_start` column exists and is a tz-aware `Datetime` column
- `t_start` is sorted ascending
- All required columns present: `['nmi', 'channel', 'flow', 'kwh', 'cadence_min']`
- No negative `kwh` values

```python
ml.validate.assert_canon(df)  # raises CanonError if invalid
```

---

### `validate_nmi(df, nmi)`

Validate or filter to a single NMI.

```python
df = ml.validate.validate_nmi(df, nmi="NMI1234567")
```

**Returns:** `pl.DataFrame` filtered to the specified NMI. Raises `ValueError` if multiple NMIs are found and none is specified, or if the specified NMI is not present.

---

## `formats`

Convert between `CanonFrame` and JSON-ready representations.

### `to_logical(df)`

Compress a `CanonFrame` into a `LogicalCanon` — a list of dicts suitable for JSON serialisation. Groups by `(nmi, channel)` and packs kWh values into per-day arrays.

```python
logical = ml.formats.to_logical(df)
# Returns: list[dict] — JSON-serialisable
```

### `from_logical(obj)`

Reconstruct a `CanonFrame` from a `LogicalCanon` object.

```python
df = ml.formats.from_logical(logical)
```

---

## `transform`

### `aggregate(df, *, freq, ...)`

Unified aggregation helper. Filters by flow, applies an optional time window, then resamples.

```python
# Daily totals per flow (wide columns)
daily = ml.transform.aggregate(df, freq="1d", groupby="flow", pivot=True)

# Monthly peak demand in kW (Mon–Fri 16:00–21:00)
demand = ml.transform.aggregate(
    df,
    freq="1MS",
    flows=["grid_import"],
    metric="kW",
    stat="max",
    out_col="demand_kw",
    window_start="16:00",
    window_end="21:00",
    window_days="MF",
)

# Seasonal totals (southern hemisphere)
seasonal = ml.transform.aggregate(
    df,
    freq="1MS",
    groupby=["season", "flow"],
    hemisphere="southern",
)
```

**Parameters:**
- `freq` (str | None) — polars duration string: `"1d"`, `"1h"`, `"30m"`, `"1MS"`, etc. Pass `None` to aggregate without resampling.
- `value_col` (str) — column to aggregate. Default: `"kwh"`
- `agg` (str) — aggregation: `"sum"`, `"mean"`, `"max"`, `"min"`. Default: `"sum"`
- `groupby` (str | list[str], optional) — additional group columns (e.g. `"flow"`, `"season"`)
- `pivot` (bool) — pivot groupby column into wide columns. Default: `False`
- `flows` (list[str], optional) — filter to these flow values before aggregating
- `window_start` / `window_end` (str, optional) — time-of-day filter `"HH:MM"`
- `window_days` (`"ALL"` | `"MF"` | `"MS"`) — day-of-week filter. Default: `"ALL"`
- `metric` (`"kWh"` | `"kW"`) — `"kW"` converts energy to power using `cadence_min`. Default: `"kWh"`
- `stat` (`"max"` | `"mean"` | `"sum"`) — stat used when `metric="kW"`. Default: `"max"`
- `out_col` (str, optional) — rename the output value column
- `hemisphere` (`"northern"` | `"southern"`, optional) — required when `groupby` includes `"season"`

**Returns:** `pl.DataFrame`

---

### `tou_bins(df, bands, *, out_freq, flows, value_col)`

Aggregate energy into named Time-of-Use bands, returning one row per month.

`bands` is a list of dicts with keys `name`, `start`, `end`. Pass `ToUBand` objects via `.model_dump()`.

```python
bands = [
    {"name": "peak",     "start": "16:00", "end": "21:00"},
    {"name": "shoulder", "start": "07:00", "end": "16:00"},
    {"name": "offpeak",  "start": "21:00", "end": "07:00"},
]
tou = ml.transform.tou_bins(df, bands)
# Columns: month, peak, shoulder, offpeak (kWh per band per month)
```

**Parameters:**
- `bands` (list[dict]) — each dict must have `name`, `start` (`"HH:MM"`), `end` (`"HH:MM"`)
- `out_freq` (str) — output frequency. Default: `"1MS"` (monthly)
- `flows` (list[str], optional) — filter to these flows. Default: `("grid_import",)`
- `value_col` (str) — column to sum. Default: `"kwh"`

**Returns:** `pl.DataFrame` with `month` (str `"YYYY-MM"`) and one column per band.

---

### `profile(df, *, flows, reducer, include_import_total)`

Build an average-day load profile grouped by time slot (`"HH:MM"`).

```python
prof = ml.transform.profile(df)
# Columns: slot, grid_import, [grid_export_solar, ...], import_total
```

**Parameters:**
- `flows` (list[str], optional) — filter to specific flows
- `reducer` (`"mean"` | `"sum"` | `"max"`) — aggregation across days. Default: `"mean"`
- `include_import_total` (bool) — add `import_total` column summing all import flows. Default: `True`

**Returns:** `pl.DataFrame` with `slot` column and one column per flow.

---

### `period_breakdown(df, *, freq, flows, cadence_min, labels)`

Compute per-period totals, peaks, and average interval kWh.

```python
daily = ml.transform.period_breakdown(df, freq="1D", cadence_min=30, labels="day")
# Returns dict with keys: "total", "peaks", "average"
# daily["total"]   — columns: day, <flow columns>, total_kwh
# daily["peaks"]   — columns: day, peak_interval_kwh
# daily["average"] — columns: day, avg_interval_kwh
```

**Parameters:**
- `freq` (`"1D"` | `"1MS"`) — daily or monthly
- `flows` (list[str], optional) — filter to specific flows
- `cadence_min` (int, optional) — used to compute `avg_interval_kwh`
- `labels` (`"day"` | `"month"`, optional) — label column name (auto-detected from freq)

**Returns:** `dict[str, pl.DataFrame]` with keys `"total"`, `"peaks"`, `"average"`.

---

### `top_n_from_profile(profile_df, *, n, value_col)`

Find the top N peak hours from an average-day profile.

```python
prof = ml.transform.profile(df)
top = ml.transform.top_n_from_profile(prof, n=4)
# Returns: {"labels": ["17", "18", "19", "20"], "value_total": 1.23, "share_pct": 28.4}
```

**Returns:** dict with `labels` (list of hour strings), `value_total` (float), `share_pct` (float).

---

## `summary`

### `summarise(df, hemisphere)`

Generate a JSON-ready summary payload for dashboards.

```python
result = ml.summary.summarise(df)
result = ml.summary.summarise(df, hemisphere="southern")  # explicit hemisphere
```

**Parameters:**
- `df` (CanonFrame)
- `hemisphere` (`"northern"` | `"southern"`, optional) — for seasonal classification. Default: `config.DEFAULT_HEMISPHERE` (`"southern"`)

**Returns:** `SummaryPayload` (TypedDict) with keys:
- `meta` — start/end dates, cadence, days
- `stats` — totals, peaks, averages
- `datasets` — profile, daily breakdown, monthly breakdown, seasonal breakdown
- `insights` — basic insight list

---

## `pricing`

### `compute_billables(df, plan, *, mode, cycles, ...)`

Compute billable quantities (TOU kWh, demand kW, export kWh) from interval data.

```python
from meterdatalogic.types import Plan, ToUBand, DemandCharge

plan = Plan(
    usage_bands=[
        ToUBand(name="peak",    start="16:00", end="21:00", rate_c_per_kwh=45.0),
        ToUBand(name="offpeak", start="21:00", end="16:00", rate_c_per_kwh=22.0),
    ],
    demand=DemandCharge(
        window_start="16:00", window_end="21:00",
        days="MF", rate_per_kw_per_month=12.0,
    ),
    fixed_c_per_day=95.0,
    feed_in_c_per_kwh=6.0,
)

# Monthly mode (one row per calendar month)
bill = ml.pricing.compute_billables(df, plan, mode="monthly")

# Cycles mode (one row per billing period)
cycles = [("2025-05-31", "2025-06-30"), ("2025-07-01", "2025-07-31")]
bill = ml.pricing.compute_billables(df, plan, mode="cycles", cycles=cycles)
```

**Parameters:**
- `plan` (Plan) — tariff plan pydantic model
- `mode` (`"monthly"` | `"cycles"`) — billing period type. Default: `"monthly"`
- `cycles` (list of (start, end) tuples) — required when `mode="cycles"`
- `include_controlled_load` (bool) — add `controlled_load_kwh` column. Default: `False`
- `include_total_import` (bool) — add `total_import_kwh` column. Default: `False`

**Returns:** `pl.DataFrame`. Monthly columns: `month`, `<band names>`, `export_kwh`, `demand_kw`. Cycles columns: `cycle`, `<band names>`, `export_kwh`, `demand_kw`, `days_in_cycle`.

---

### `estimate_costs(bill, plan, *, pay_on_time_discount, include_gst, gst_rate)`

Estimate dollar costs from a billables DataFrame.

```python
costs = ml.pricing.estimate_costs(bill, plan)

costs = ml.pricing.estimate_costs(
    bill,
    plan,
    pay_on_time_discount=0.07,   # 7% discount
    include_gst=True,
    gst_rate=0.10,
)
```

**Parameters:**
- `bill` (pl.DataFrame) — output from `compute_billables`
- `plan` (Plan) — tariff plan (rates used for cost calculation)
- `pay_on_time_discount` (float) — fractional discount applied to charges. Default: `0.0`
- `include_gst` (bool, optional) — include GST. Default: `config.INCLUDE_GST` (`False`)
- `gst_rate` (float, optional) — GST rate. Default: `config.GST_RATE` (`0.10`)

**Returns:** `pl.DataFrame` with columns: `month` or `cycle`, `energy_cost`, `demand_cost`, `fixed_cost`, `feed_in_credit`, `pay_on_time_discount`, `gst`, `total`.

---

## `scenario`

### `run(df, *, ev, pv, battery, plan)`

Simulate EV charging, PV generation, and battery storage against a baseline load.

```python
ev = ml.types.EVConfig(
    daily_kwh=8.0, max_kw=7.0,
    window_start="18:00", window_end="22:00",
    days="ALL", strategy="immediate",
)
pv = ml.types.PVConfig(
    system_kwp=6.6, inverter_kw=5.0,
    loss_fraction=0.15,
    seasonal_scale={"01": 1.05, "06": 0.90},
)
bat = ml.types.BatteryConfig(
    capacity_kwh=10.0, max_kw=5.0,
    round_trip_eff=0.9, soc_min=0.1, soc_max=0.95,
)

result = ml.scenario.run(df, ev=ev, pv=pv, battery=bat, plan=plan)
```

All device parameters are optional — pass only the components you want to model.

**Returns:** `ScenarioResult` TypedDict with `before`, `after` DataFrames, `summary`, `costs` (if plan provided), and `deltas`.

---

## `insights`

### `generate_insights(df, ...)`

Run all configured evaluators and return a list of insights.

```python
insights = ml.insights.generate_insights(df)

for i in insights:
    print(i.title, i.severity, i.category)
```

**Returns:** `list[Insight]`

Each `Insight` has: `title`, `message`, `severity` (`"info"` | `"notice"` | `"warning"` | `"critical"`), `category` (`"usage"` | `"tariff"` | `"solar"` | `"scenario"` | `"data_quality"`), `tags`, `metrics`, `extras`.

---

## `config`

Package-level configuration defaults. Override before calling functions.

```python
import meterdatalogic as ml

ml.config.DEFAULT_TZ = "Australia/Sydney"
ml.config.DEFAULT_HEMISPHERE = "southern"
ml.config.GST_RATE = 0.10
ml.config.INCLUDE_GST = False
```

---

## Types (`ml.types`)

### `ToUBand`

```python
ml.types.ToUBand(
    name="peak",
    start="16:00",       # "HH:MM"
    end="21:00",         # "HH:MM"
    rate_c_per_kwh=45.0,
)
```

### `DemandCharge`

```python
ml.types.DemandCharge(
    window_start="16:00",
    window_end="21:00",
    days="MF",                      # "MF" (Mon–Fri) or "MS" (Mon–Sun)
    rate_per_kw_per_month=12.0,
)
```

### `Plan`

```python
ml.types.Plan(
    usage_bands=[...],       # list[ToUBand]
    demand=None,             # DemandCharge | None
    fixed_c_per_day=95.0,
    feed_in_c_per_kwh=6.0,
)
```

### `EVConfig`

```python
ml.types.EVConfig(
    daily_kwh=8.0,
    max_kw=7.0,
    window_start="18:00",
    window_end="22:00",
    days="ALL",            # "ALL", "MF", or "MS"
    strategy="immediate",  # "immediate" or "off_peak"
)
```

### `PVConfig`

```python
ml.types.PVConfig(
    system_kwp=6.6,
    inverter_kw=5.0,
    loss_fraction=0.15,
    seasonal_scale={"01": 1.05, "06": 0.90},  # month string → scale factor
)
```

### `BatteryConfig`

```python
ml.types.BatteryConfig(
    capacity_kwh=10.0,
    max_kw=5.0,
    round_trip_eff=0.9,
    soc_min=0.1,
    soc_max=0.95,
)
```
