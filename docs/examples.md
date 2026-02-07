# Examples & Use Cases

Practical recipes for common meterdatalogic workflows.

> **Note:** All examples use the standard import pattern: `import meterdatalogic as ml`

---

## Data Loading

### Load NEM12 File

```python
import meterdatalogic as ml

# Load NEM12 file (automatically validates)
df = ml.ingest.from_nem12("data/sample.csv", tz="Australia/Brisbane")

print(f"Loaded {len(df)} intervals")
print(f"NMIs: {df['nmi'].unique()}")
print(f"Flows: {df['flow'].unique()}")
print(f"Date range: {df.index.min()} to {df.index.max()}")
```

### Load Custom CSV

```python
import pandas as pd
import meterdatalogic as ml

# Load raw CSV
raw_df = pd.read_csv("data/meter_export.csv", parse_dates=["timestamp"])

# Normalize to canonical format
df = ml.ingest.from_dataframe(
    raw_df,
    tz="Australia/Sydney",
    nmi="NMI1234567",
    flow="grid_import"
)

# Validate
ml.validate.assert_canon(df)
```

### Load from Database

```python
import psycopg2
import pandas as pd
import meterdatalogic as ml

# Query database
conn = psycopg2.connect("dbname=meters user=readonly")
raw_df = pd.read_sql("""
    SELECT timestamp, nmi, channel, kwh
    FROM meter_intervals
    WHERE nmi = 'NMI1234567'
    AND timestamp >= '2025-01-01'
    ORDER BY timestamp
""", conn)

# Normalize
df = ml.ingest.from_dataframe(raw_df, tz="Australia/Brisbane")
```

---

## Data Transformation

### Daily Totals

```python
# Daily energy totals per flow
daily = ml.transform.aggregate(df, freq="1D", how="sum")

print(daily.groupby("flow")["kwh"].sum())
```

### Hourly Average Power

```python
# Hourly average with power calculation
hourly = ml.transform.aggregate(
    df,
    freq="1H",
    how="mean",
    add_power=True,
    power_col="kw"
)

print(hourly[["kwh", "kw"]].head())
```

### Time-of-Use Classification

```python
from meterdatalogic.types import TouBand

# Define TOU bands
bands = [
    TouBand(
        label="peak",
        weekdays=[0, 1, 2, 3, 4],  # Monday-Friday
        start_hour=14,
        end_hour=20
    ),
    TouBand(
        label="shoulder",
        weekdays=[0, 1, 2, 3, 4],
        start_hour=7,
        end_hour=14
    ),
    TouBand(
        label="offpeak",
        weekdays=None,  # All days
        start_hour=None,  # All other hours
        end_hour=None
    )
]

# Classify intervals
df_tou = ml.transform.tou_bins(df, bands)

# Aggregate by TOU band
tou_summary = df_tou.groupby(["flow", "tou_label"])["kwh"].sum()
print(tou_summary)
```

### Monthly Breakdown

```python
# Monthly totals by flow
monthly = ml.transform.aggregate(df, freq="MS", groupby=["flow"])

# Add month labels
monthly["month"] = monthly.index.strftime("%b %Y")

print(monthly.pivot(columns="flow", values="kwh"))
```

---

## Summaries

### Daily Profile

```python
# Get daily summary
summary = ml.summary.daily_summary(df)

print(f"Total import: {summary['total_import_kwh']:.1f} kWh")
print(f"Avg daily: {summary['avg_daily_kwh']:.1f} kWh")
print(f"Peak day: {summary['peak_day']}")
```

### 24-Hour Load Profile

```python
# Get hourly profile
profile = ml.summary.profile24(df, flow="grid_import")

# Plot
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 5))
plt.plot(profile["hour"], profile["avg_kwh"])
plt.xlabel("Hour of Day")
plt.ylabel("Average kWh")
plt.title("24-Hour Load Profile")
plt.grid(True)
plt.show()
```

### Peak Demand

```python
# Find top 10 peak intervals
peaks = ml.summary.peaks(df, top_n=10)

for i, peak in enumerate(peaks, 1):
    print(f"{i}. {peak['timestamp']}: {peak['kwh']:.2f} kWh ({peak['kw']:.2f} kW)")
```

---

## Pricing

### Basic Bill Calculation

```python
# Define plan
plan = {
    "billing_cycle": "monthly",
    "demand_window": "30D",
    "demand_method": "rolling_avg"
}

# Define tariff
tariff = {
    "usage_rate": 0.28,      # $/kWh
    "daily_charge": 1.20,     # $/day
    "demand_rate": 12.50,     # $/kW
    "gst": 0.10,              # 10% GST
    "discount": 0.05          # 5% pay-on-time
}

# Calculate billables
billables = ml.pricing.compute_billables(df, plan, mode="monthly")

# Estimate costs
costs = ml.pricing.estimate_costs(billables, tariff)

print(costs[["period", "usage_charge", "demand_charge", "daily_charge", "total"]])
```

### TOU Pricing

```python
from meterdatalogic.types import TouBand

# Define TOU plan
bands = [
    TouBand(label="peak", weekdays=[0,1,2,3,4], start_hour=14, end_hour=20),
    TouBand(label="shoulder", weekdays=[0,1,2,3,4], start_hour=7, end_hour=14),
    TouBand(label="offpeak", weekdays=None, start_hour=None, end_hour=None)
]

plan = {
    "billing_cycle": "monthly",
    "tou_bands": bands
}

# TOU tariff
tariff = {
    "usage_rates": {
        "peak": 0.45,
        "shoulder": 0.28,
        "offpeak": 0.18
    },
    "daily_charge": 1.20,
    "gst": 0.10
}

# Calculate with TOU
billables = ml.pricing.compute_billables(df, plan)
costs = ml.pricing.estimate_costs(billables, tariff)

print(f"Peak usage: {billables['peak_kwh'].sum():.1f} kWh @ ${tariff['usage_rates']['peak']}/kWh")
print(f"Total cost: ${costs['total'].sum():.2f}")
```

### Solar Feed-in

```python
# Tariff with feed-in
tariff = {
    "usage_rate": 0.28,
    "feed_in_rate": 0.08,    # Solar export credit
    "daily_charge": 1.20,
    "gst": 0.10
}

billables = ml.pricing.compute_billables(df, plan)
costs = ml.pricing.estimate_costs(billables, tariff)

# Check export credit
export_credit = billables["export_kwh"].sum() * tariff["feed_in_rate"]
print(f"Solar export credit: ${export_credit:.2f}")
```

---

## Scenario Modeling

### Solar PV Analysis

```python
# Define solar scenario
config = {
    "pv": {
        "capacity_kw": 6.6,
        "orientation": "north",
        "efficiency": 0.85
    }
}

# Run scenario
scenario_df = ml.scenario.run(df, config)

# Compare import
baseline_import = df[df["flow"] == "grid_import"]["kwh"].sum()
scenario_import = scenario_df[scenario_df["flow"] == "grid_import_scenario"]["kwh"].sum()

reduction_pct = (1 - scenario_import / baseline_import) * 100
print(f"Grid import reduced by {reduction_pct:.1f}%")

# Calculate savings
baseline_cost = baseline_import * 0.28
scenario_cost = scenario_import * 0.28
annual_savings = (baseline_cost - scenario_cost) * 365/90  # Scale to annual

system_cost = 6.6 * 1200  # $1200/kW installed
payback = system_cost / annual_savings

print(f"Annual savings: ${annual_savings:.0f}")
print(f"Payback period: {payback:.1f} years")
```

### Solar + Battery

```python
config = {
    "pv": {
        "capacity_kw": 6.6,
        "orientation": "north",
        "efficiency": 0.85
    },
    "battery": {
        "capacity_kwh": 13.5,
        "max_charge_kw": 5.0,
        "max_discharge_kw": 5.0,
        "efficiency": 0.90,
        "charge_strategy": "solar_first",
        "discharge_strategy": "peak_shave"
    }
}

scenario_df = ml.scenario.run(df, config)

# Check battery utilization
battery_charge = scenario_df[scenario_df["flow"] == "battery_charge"]["kwh"].sum()
battery_discharge = scenario_df[scenario_df["flow"] == "battery_discharge"]["kwh"].sum()
cycles = battery_charge / 13.5

print(f"Battery charged: {battery_charge:.1f} kWh")
print(f"Battery discharged: {battery_discharge:.1f} kWh")
print(f"Equivalent cycles: {cycles:.1f}")
```

### Compare Multiple Scenarios

```python
scenarios = {
    "baseline": None,
    "solar_6kw": {"pv": {"capacity_kw": 6.6}},
    "solar_10kw": {"pv": {"capacity_kw": 10}},
    "solar_battery": {
        "pv": {"capacity_kw": 6.6},
        "battery": {"capacity_kwh": 13.5, "max_charge_kw": 5, "max_discharge_kw": 5}
    }
}

results = {}
for name, config in scenarios.items():
    if config is None:
        scenario_df = df
    else:
        scenario_df = ml.scenario.run(df, config)
    
    # Calculate cost
    billables = ml.pricing.compute_billables(scenario_df, plan)
    costs = ml.pricing.estimate_costs(billables, tariff)
    
    results[name] = {
        "annual_cost": costs["total"].sum() * 12/len(costs),
        "import_kwh": scenario_df[scenario_df["flow"].str.contains("import")]["kwh"].sum()
    }

# Display comparison
import pandas as pd
pd.DataFrame(results).T
```

---

## Insights

### Generate Insights

```python
# Basic insights
insights = ml.insights.generate_insights(df)

# Display by level
for level in ["alert", "recommendation", "opportunity", "observation"]:
    level_insights = [i for i in insights if i.level == level]
    if level_insights:
        print(f"\n{level.upper()}S:")
        for insight in level_insights:
            print(f"  • {insight.message}")
```

### Insights with Pricing

```python
# Calculate pricing
plan = {...}
tariff = {...}
billables = ml.pricing.compute_billables(df, plan)
costs = ml.pricing.estimate_costs(billables, tariff)

# Generate insights with pricing context
insights = ml.insights.generate_insights(
    df,
    pricing_context={
        "plan": plan,
        "billables": billables,
        "costs": costs
    }
)

# Filter cost opportunities
cost_insights = [i for i in insights if i.category == "cost" and i.level in ["opportunity", "recommendation"]]
for insight in cost_insights:
    print(f"💡 {insight.message}")
    if "savings" in insight.metadata:
        print(f"   Potential savings: ${insight.metadata['savings']:.0f}/year")
```

### Custom Insight Config

```python
from meterdatalogic.insights import InsightConfig

config = InsightConfig(
    enable_basic=True,
    enable_intermediate=True,
    enable_advanced=False,  # Disable expensive evaluators
    thresholds={
        "high_usage_kwh_per_day": 30,  # Adjust for your customers
        "peak_time_ratio": 0.5
    }
)

insights = ml.insights.generate_insights(df, config=config)
```

---

## Export Formats

### To JSON

```python
# Convert to JSON-ready format
logical = ml.formats.to_logical(df)

import json
with open("meter_data.json", "w") as f:
    json.dump(logical, f, indent=2)
```

### From JSON

```python
# Load from JSON
import json
with open("meter_data.json") as f:
    logical = json.load(f)

# Convert back to CanonFrame
df = ml.formats.from_logical(logical, tz="Australia/Brisbane")
```

### To CSV

```python
# Export canonical data
df.to_csv("meter_data.csv")

# Load back
import pandas as pd
loaded = pd.read_csv("meter_data.csv", index_col=0, parse_dates=True)
loaded.index = loaded.index.tz_localize("Australia/Brisbane")
loaded.index.name = "t_start"

ml.validate.assert_canon(loaded)
```

---

## Integration Patterns

### Django View

```python
from django.http import JsonResponse
import meterdatalogic as ml

def meter_summary_view(request, nmi):
    # Load from database
    intervals = MeterInterval.objects.filter(nmi=nmi).order_by("timestamp")
    raw_df = pd.DataFrame(list(intervals.values()))
    
    # Normalize
    df = ml.ingest.from_dataframe(raw_df, tz="Australia/Brisbane")
    
    # Generate summary
    summary = ml.summary.daily_summary(df)
    
    return JsonResponse(summary)
```

### FastAPI Endpoint

```python
from fastapi import FastAPI, UploadFile
import meterdatalogic as ml

app = FastAPI()

@app.post("/analyze")
async def analyze_meter_data(file: UploadFile):
    # Load uploaded NEM12
    content = await file.read()
    with open("/tmp/upload.csv", "wb") as f:
        f.write(content)
    
    df = ml.ingest.from_nem12("/tmp/upload.csv")
    
    # Generate insights
    insights = ml.insights.generate_insights(df)
    
    return {
        "total_intervals": len(df),
        "date_range": {
            "start": df.index.min().isoformat(),
            "end": df.index.max().isoformat()
        },
        "insights": [
            {
                "level": i.level,
                "message": i.message,
                "confidence": i.confidence
            }
            for i in insights
        ]
    }
```

### Airflow DAG

```python
from airflow import DAG
from airflow.operators.python import PythonOperator
import meterdatalogic as ml

def process_meter_data(**context):
    nmi = context["params"]["nmi"]
    
    # Load data
    df = load_from_s3(f"meter-data/{nmi}.csv")
    df = ml.ingest.from_dataframe(df)
    
    # Calculate pricing
    plan = load_tariff_plan(nmi)
    billables = ml.pricing.compute_billables(df, plan)
    
    # Save results
    save_to_database(nmi, billables)

with DAG("meter_processing", schedule_interval="@daily") as dag:
    process_task = PythonOperator(
        task_id="process_meter_data",
        python_callable=process_meter_data,
        params={"nmi": "{{ nmi }}"}
    )
```

---

## Troubleshooting

### Timezone Issues

```python
# Check timezone
print(f"Timezone: {df.index.tz}")

# Convert if needed
df.index = df.index.tz_convert("Australia/Sydney")

# Localize if naive
if df.index.tz is None:
    df.index = df.index.tz_localize("Australia/Brisbane")
```

### Missing Data Gaps

```python
# Find gaps
expected_intervals = len(pd.date_range(
    df.index.min(),
    df.index.max(),
    freq="30min"
))
actual_intervals = len(df)
missing = expected_intervals - actual_intervals

print(f"Missing {missing} intervals ({missing/expected_intervals*100:.1f}%)")

# Fill gaps (use with caution!)
full_index = pd.date_range(
    df.index.min(),
    df.index.max(),
    freq="30min",
    tz=df.index.tz,
    name="t_start"
)
df = df.reindex(full_index)
df[["nmi", "channel", "flow", "cadence_min"]] = df[["nmi", "channel", "flow", "cadence_min"]].ffill()
df["kwh"] = df["kwh"].fillna(0)  # Or interpolate
```

### Memory Issues

```python
# Process in chunks for large datasets
chunk_size = 100000
results = []

for chunk in pd.read_csv("large_file.csv", chunksize=chunk_size):
    df = ml.ingest.from_dataframe(chunk)
    daily = ml.transform.aggregate(df, freq="1D")
    results.append(daily)

combined = pd.concat(results)
```
