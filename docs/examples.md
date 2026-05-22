# Examples & Use Cases

Practical recipes for common meterdatalogic workflows.

> All examples use the standard import pattern: `import meterdatalogic as ml`
> All DataFrames are `polars.DataFrame` — there is no pandas dependency.

---

## Data Loading

### Load NEM12 File

```python
import meterdatalogic as ml

df = ml.ingest.from_nem12("data/sample.csv", tz="Australia/Brisbane")

print(f"Loaded {len(df)} intervals")
print(f"NMIs: {df['nmi'].unique().to_list()}")
print(f"Flows: {df['flow'].unique().to_list()}")
print(f"Date range: {df['t_start'].min()} to {df['t_start'].max()}")
```

### Load Custom CSV

```python
import polars as pl
import meterdatalogic as ml

raw = pl.read_csv("data/meter_export.csv", try_parse_dates=True)

df = ml.ingest.from_dataframe(
    raw,
    tz="Australia/Sydney",
    nmi="NMI1234567",
)

ml.validate.assert_canon(df)
```

### Load from Database (psycopg2 example)

```python
import psycopg2
import polars as pl
import meterdatalogic as ml

conn = psycopg2.connect("dbname=meters user=readonly")
cur = conn.cursor()
cur.execute("""
    SELECT timestamp, nmi, channel, kwh
    FROM meter_intervals
    WHERE nmi = 'NMI1234567'
    AND timestamp >= '2025-01-01'
    ORDER BY timestamp
""")
rows = cur.fetchall()
cols = [d[0] for d in cur.description]

raw = pl.DataFrame(rows, schema=cols, orient="row")
df = ml.ingest.from_dataframe(raw, tz="Australia/Brisbane")
```

---

## Data Transformation

### Daily Totals by Flow

```python
# Daily energy totals, one column per flow
daily = ml.transform.aggregate(df, freq="1d", groupby="flow", pivot=True)
# Columns: t_start, grid_import, grid_export_solar, ...
```

### Monthly Totals

```python
monthly = ml.transform.aggregate(df, freq="1MS", groupby="flow", pivot=True)
# Columns: t_start, grid_import, grid_export_solar, ...
```

### Monthly Peak Demand (kW)

```python
# Max kW during Mon–Fri 16:00–21:00 window, per month
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
# Columns: t_start, demand_kw
```

### Time-of-Use Band Aggregation

```python
bands = [
    {"name": "peak",     "start": "16:00", "end": "21:00"},
    {"name": "shoulder", "start": "07:00", "end": "16:00"},
    {"name": "offpeak",  "start": "21:00", "end": "07:00"},
]

tou = ml.transform.tou_bins(df, bands)
# Columns: month (YYYY-MM), peak, shoulder, offpeak (kWh per band per month)
print(tou)
```

### Seasonal Breakdown

```python
seasonal = ml.transform.aggregate(
    df,
    freq="1MS",
    groupby=["season", "flow"],
    hemisphere="southern",
    pivot=False,
)
# Columns: t_start, season, year, kwh
```

### Average-Day Load Profile

```python
prof = ml.transform.profile(df)
# Columns: slot (HH:MM), grid_import, [grid_export_solar, ...], import_total

# Top 4 peak hours
top = ml.transform.top_n_from_profile(prof, n=4)
print(top["labels"])    # e.g. ["17", "18", "19", "20"]
print(top["share_pct"]) # e.g. 32.5
```

### Daily/Monthly Breakdown

```python
daily = ml.transform.period_breakdown(df, freq="1D", cadence_min=30)
# daily["total"]   — columns: day, grid_import, ..., total_kwh
# daily["peaks"]   — columns: day, peak_interval_kwh
# daily["average"] — columns: day, avg_interval_kwh

monthly = ml.transform.period_breakdown(df, freq="1MS", cadence_min=30)
# monthly["total"]["month"], monthly["peaks"]["month"], etc.
```

---

## Summary

### Full Dashboard Payload

```python
result = ml.summary.summarise(df)

print(result["meta"])      # start, end, cadence_min, days
print(result["stats"])     # totals, peaks, per_day_avg
print(result["datasets"])  # profile, daily, monthly, seasonal
```

---

## Pricing

### Define a Plan

```python
from meterdatalogic.types import Plan, ToUBand, DemandCharge

plan = Plan(
    usage_bands=[
        ToUBand(name="peak",     start="16:00", end="21:00", rate_c_per_kwh=45.0),
        ToUBand(name="shoulder", start="07:00", end="16:00", rate_c_per_kwh=28.0),
        ToUBand(name="offpeak",  start="21:00", end="07:00", rate_c_per_kwh=22.0),
    ],
    demand=DemandCharge(
        window_start="16:00", window_end="21:00",
        days="MF", rate_per_kw_per_month=12.0,
    ),
    fixed_c_per_day=95.0,
    feed_in_c_per_kwh=6.0,
)
```

### Monthly Bill Estimate

```python
bill = ml.pricing.compute_billables(df, plan, mode="monthly")
# Columns: month, peak, shoulder, offpeak, export_kwh, demand_kw

costs = ml.pricing.estimate_costs(bill, plan)
# Columns: month, energy_cost, demand_cost, fixed_cost, feed_in_credit,
#          pay_on_time_discount, gst, total

print(costs.select(["month", "total"]))
```

### Bill with GST and Pay-on-Time Discount

```python
costs = ml.pricing.estimate_costs(
    bill,
    plan,
    pay_on_time_discount=0.07,
    include_gst=True,
)
```

### Custom Billing Cycles

```python
cycles = [
    ("2025-05-31", "2025-06-30"),
    ("2025-07-01", "2025-07-31"),
    ("2025-08-01", "2025-08-31"),
]

bill = ml.pricing.compute_billables(df, plan, mode="cycles", cycles=cycles)
# Columns: cycle, peak, shoulder, offpeak, export_kwh, demand_kw, days_in_cycle

costs = ml.pricing.estimate_costs(bill, plan)
```

### Include Controlled Load

```python
bill = ml.pricing.compute_billables(
    df,
    plan,
    mode="monthly",
    include_controlled_load=True,
    include_total_import=True,
)
# Additional columns: controlled_load_kwh, total_import_kwh
```

---

## Scenarios

### Solar PV Only

```python
pv = ml.types.PVConfig(
    system_kwp=6.6,
    inverter_kw=5.0,
    loss_fraction=0.15,
)

result = ml.scenario.run(df, pv=pv, plan=plan)
print(result["deltas"])   # import reduction, self-consumption, etc.
print(result["costs"])    # before/after cost comparison
```

### EV + Battery + PV

```python
ev = ml.types.EVConfig(
    daily_kwh=8.0, max_kw=7.0,
    window_start="18:00", window_end="22:00",
    days="ALL", strategy="immediate",
)
pv = ml.types.PVConfig(
    system_kwp=6.6, inverter_kw=5.0, loss_fraction=0.15,
    seasonal_scale={"01": 1.05, "06": 0.90},
)
bat = ml.types.BatteryConfig(
    capacity_kwh=10.0, max_kw=5.0,
    round_trip_eff=0.9, soc_min=0.1, soc_max=0.95,
)

result = ml.scenario.run(df, ev=ev, pv=pv, battery=bat, plan=plan)
```

---

## Insights

```python
insights = ml.insights.generate_insights(df)

for i in insights:
    print(f"[{i.severity.upper()}] {i.title}: {i.message}")
```

Filter by category:

```python
usage_insights = [i for i in insights if i.category == "usage"]
tariff_insights = [i for i in insights if i.category == "tariff"]
```

---

## Format Conversion

### Export to JSON

```python
logical = ml.formats.to_logical(df)

import json
with open("output.json", "w") as f:
    json.dump(logical, f)
```

### Reconstruct from JSON

```python
import json

with open("output.json") as f:
    logical = json.load(f)

df = ml.formats.from_logical(logical)
ml.validate.assert_canon(df)
```

---

## Configuration

Override package defaults at import time:

```python
import meterdatalogic as ml

ml.config.DEFAULT_TZ = "Australia/Sydney"
ml.config.DEFAULT_HEMISPHERE = "southern"
ml.config.INCLUDE_GST = True
ml.config.GST_RATE = 0.10
```
