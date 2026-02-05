# API Reference

Complete reference for all modules in meterdatalogic.

---

## Core Modules

### `canon`

Canonical schema constants and normalization.

**Constants:**
- `INDEX_NAME = "t_start"` - Required index name for all CanonFrame DataFrames
- `DEFAULT_TZ = "Australia/Brisbane"` - Default timezone (no DST)
- `DEFAULT_CADENCE = 30` - Default interval minutes

**Functions:**
- `from_nem12(path: str, tz: str = DEFAULT_TZ) -> CanonFrame` - Load NEM12 file to canonical format
- `from_dataframe(df: pd.DataFrame, tz: str = DEFAULT_TZ) -> CanonFrame` - Normalize raw DataFrame

---

### `ingest`

Load and normalize raw meter data from various sources.

**Functions:**

#### `from_dataframe(df, tz="Australia/Brisbane", nmi=None, channel=None, flow=None, cadence_min=None)`

Normalize a raw DataFrame to canonical format.

**Parameters:**
- `df` (DataFrame): Raw data with datetime column and energy readings
- `tz` (str): Timezone for naive timestamps
- `nmi` (str, optional): NMI identifier, auto-detected if missing
- `channel` (str, optional): Channel label (e.g., "E1", "B1")
- `flow` (str, optional): Flow type (grid_import, controlled_load_import, grid_export_solar)
- `cadence_min` (int, optional): Interval minutes, auto-detected if missing

**Returns:** CanonFrame with validated schema

**Example:**
```python
import meterdatalogic as ml

df = ml.ingest.from_dataframe(
    raw_df,
    tz="Australia/Sydney",
    nmi="NMI1234567",
    flow="grid_import"
)
```

#### `from_nem12(path, tz="Australia/Brisbane")`

Parse a NEM12 file and return canonical DataFrame.

**Parameters:**
- `path` (str): File path to NEM12 CSV
- `tz` (str): Timezone for interpretation

**Returns:** CanonFrame with all channels from the file

**Example:**
```python
df = ml.ingest.from_nem12("data/sample.csv")
```

#### `from_json(data, tz="Australia/Brisbane")`

Load canonical data from JSON-ready format.

**Parameters:**
- `data` (dict): LogicalCanon dictionary
- `tz` (str): Timezone to apply

**Returns:** CanonFrame

---

### `validate`

Schema validation and enforcement.

**Functions:**

#### `assert_canon(df)`

Validate that DataFrame conforms to canonical schema. Raises `CanonError` on violations.

**Checks:**
- Index is DatetimeIndex named "t_start"
- Index is tz-aware and sorted
- Required columns present: ['nmi', 'channel', 'flow', 'kwh', 'cadence_min']
- No duplicate timestamps per (nmi, channel)
- cadence_min values are consistent per (nmi, channel)

**Raises:** `CanonError` with descriptive message

**Example:**
```python
ml.validate.assert_canon(df)  # Raises if invalid
```

#### `ensure(df)`

Light validation - returns True if canonical, False otherwise. No exceptions.

**Returns:** bool

---

### `transform`

Data transformation, aggregation, and filtering.

**Functions:**

#### `aggregate(df, freq, how="sum", groupby=None, add_power=False, power_col="kw")`

Unified aggregation function for resampling and grouping.

**Parameters:**
- `df` (CanonFrame): Input data
- `freq` (str): Pandas frequency string ("1D", "1H", "30min", "MS", etc.)
- `how` (str): Aggregation method - "sum", "mean", "max", "min"
- `groupby` (list[str], optional): Additional columns to group by (e.g., ["flow"])
- `add_power` (bool): If True, calculate average power (kW) from kWh
- `power_col` (str): Name for power column if add_power=True

**Returns:** Aggregated CanonFrame

**Examples:**
```python
# Daily totals
daily = ml.transform.aggregate(df, freq="1D", how="sum")

# Hourly by flow
hourly = ml.transform.aggregate(df, freq="1H", groupby=["flow"])

# With power calculation
daily = ml.transform.aggregate(df, freq="1D", add_power=True)
```

#### `tou_bins(df, bands)`

Classify intervals into Time-of-Use bands.

**Parameters:**
- `df` (CanonFrame): Input data
- `bands` (list[TouBand]): List of TOU band definitions

**Returns:** CanonFrame with added 'tou_label' column

**Example:**
```python
from meterdatalogic.types import TouBand

bands = [
    TouBand(label="peak", weekdays=[0,1,2,3,4], start_hour=14, end_hour=20),
    TouBand(label="shoulder", weekdays=[0,1,2,3,4], start_hour=7, end_hour=14),
    TouBand(label="offpeak", weekdays=None, start_hour=None, end_hour=None)
]

df_tou = ml.transform.tou_bins(df, bands)
```

#### `profile(df, n=24, groupby=None, how="mean")`

Generate time-of-day profile (24-hour average).

**Parameters:**
- `df` (CanonFrame): Input data
- `n` (int): Number of buckets (default 24 for hourly)
- `groupby` (list[str], optional): Group columns
- `how` (str): Aggregation method

**Returns:** DataFrame with 'hour_of_day' and aggregated values

#### `period_breakdown(df, freq, groupby=None, how="sum")`

Break down data by period (daily, monthly, etc.).

**Parameters:**
- `df` (CanonFrame): Input data
- `freq` (str): Period frequency
- `groupby` (list[str], optional): Additional grouping
- `how` (str): Aggregation method

**Returns:** Aggregated DataFrame

---

### `summary`

JSON-ready summaries and rollups.

**Functions:**

#### `daily_summary(df)`

Daily energy totals per flow.

**Returns:** Dictionary with daily kWh by flow type

#### `monthly_summary(df)`

Monthly energy totals and statistics.

**Returns:** Dictionary with monthly rollups

#### `profile24(df, flow=None)`

24-hour load profile.

**Parameters:**
- `df` (CanonFrame): Input data
- `flow` (str, optional): Filter to specific flow type

**Returns:** Dictionary with hourly averages

#### `peaks(df, top_n=10)`

Find peak demand intervals.

**Parameters:**
- `df` (CanonFrame): Input data
- `top_n` (int): Number of top intervals to return

**Returns:** Dictionary with peak timestamps and values

---

### `pricing`

Tariff calculations and billing.

**Functions:**

#### `compute_billables(df, plan, mode="monthly", tz=None)`

Calculate billable quantities for energy charges.

**Parameters:**
- `df` (CanonFrame): Input meter data
- `plan` (dict): Tariff plan configuration
- `mode` (str): "monthly" or "cycles" (custom billing periods)
- `tz` (str, optional): Override timezone

**Returns:** DataFrame with billable quantities per period

**Plan Structure:**
```python
plan = {
    "demand_window": "30D",  # Rolling demand window
    "demand_method": "rolling_avg",  # or "peak"
    "billing_cycle": "monthly",  # or list of cycle dates
    "tou_bands": [...],  # TOU band definitions
}
```

#### `estimate_costs(billables, tariff)`

Calculate costs from billables and tariff rates.

**Parameters:**
- `billables` (DataFrame): Output from compute_billables
- `tariff` (dict): Rate structure

**Returns:** DataFrame with cost breakdown

**Tariff Structure:**
```python
tariff = {
    "usage_rates": {
        "peak": 0.35,
        "shoulder": 0.25,
        "offpeak": 0.15
    },
    "demand_rate": 15.0,  # $/kW
    "daily_charge": 1.20,
    "feed_in_rate": 0.08,
    "gst": 0.10,
    "discount": 0.05  # Pay-on-time discount
}
```

---

### `scenario`

What-if modeling for solar, battery, and EV.

**Functions:**

#### `run(df, config)`

Run scenario simulation with PV/battery/EV models.

**Parameters:**
- `df` (CanonFrame): Base meter data (grid import)
- `config` (dict): Scenario configuration

**Returns:** CanonFrame with modeled flows

**Config Structure:**
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
        "efficiency": 0.90
    },
    "ev": {
        "capacity_kwh": 75,
        "charge_power_kw": 7.0,
        "charge_schedule": "offpeak"
    }
}
```

---

### `insights`

Pattern detection and recommendations.

**Functions:**

#### `generate_insights(df, config=None, pricing_context=None, scenarios_context=None)`

Generate insights from meter data, pricing, and scenarios.

**Parameters:**
- `df` (CanonFrame): Input meter data
- `config` (InsightConfig, optional): Evaluator configuration
- `pricing_context` (PricingContext, optional): Pricing data for analysis
- `scenarios_context` (ScenariosContext, optional): Scenario results

**Returns:** List of Insight objects

**Example:**
```python
insights = ml.insights.generate_insights(
    df,
    pricing_context={
        "plan": plan,
        "billables": billables,
        "costs": costs
    }
)

for insight in insights:
    print(f"{insight.level}: {insight.message}")
```

**Insight Levels:**
- `observation` - Neutral data pattern
- `opportunity` - Potential for optimization
- `recommendation` - Actionable suggestion
- `alert` - Requires attention

---

### `formats`

Convert between CanonFrame and JSON-ready formats.

**Functions:**

#### `to_logical(df)`

Convert CanonFrame to JSON-ready LogicalCanon format.

**Returns:** Dictionary with timezone-naive ISO strings

#### `from_logical(data, tz="Australia/Brisbane")`

Convert LogicalCanon to CanonFrame.

**Parameters:**
- `data` (dict): LogicalCanon dictionary
- `tz` (str): Timezone to apply

**Returns:** CanonFrame

---

### `utils`

Helper functions.

**Functions:**

#### `month_label(dt)`

Generate human-readable month label.

**Example:** "Jan 2025"

#### `build_canon_frame(data, tz="Australia/Brisbane")`

Construct a CanonFrame from dictionary data.

---

## Types

### `CanonFrame`

Type alias for `pd.DataFrame` with canonical schema.

### `TouBand`

TypedDict for Time-of-Use band definition:
```python
{
    "label": str,
    "weekdays": list[int] | None,  # 0=Mon, 6=Sun, None=all days
    "start_hour": int | None,
    "end_hour": int | None  # 24-hour format
}
```

### `Flow`

Literal type: `"grid_import" | "controlled_load_import" | "grid_export_solar"`

### `Plan`

TypedDict for tariff plan configuration.

### `Insight`

Dataclass for insight results:
```python
@dataclass
class Insight:
    level: InsightLevel
    category: InsightCategory
    message: str
    severity: InsightSeverity
    confidence: float
    metadata: dict
```

---

## Exceptions

### `CanonError`

Raised when DataFrame violates canonical schema requirements.

**Common causes:**
- Missing required columns
- Index not DatetimeIndex or not named "t_start"
- Timezone-naive timestamps
- Duplicate timestamps
- Unsorted index
- Inconsistent cadence values

**Example:**
```python
try:
    ml.validate.assert_canon(df)
except ml.exceptions.CanonError as e:
    print(f"Schema violation: {e}")
```
