# Pricing Testing Plan

## Purpose
To validate the accuracy, robustness, and consistency of the pricing engine across different NEM12 datasets and retail plan configurations. This ensures that calculated costs match retailer bills within acceptable rounding tolerances and that edge cases (e.g., varying cadences, DST changes, and complex TOU plans) are handled gracefully.

---

## Objectives
- Verify correct handling of **bill periods** (inclusive/exclusive boundaries).
- Confirm energy, fixed, demand, and feed-in charges match expected calculations.
- Validate **pay-on-time discount** and **GST** logic matches retailer invoicing.
- Ensure **TOU banding** and **demand windowing** are applied correctly per configuration.
- Maintain consistent results for both **cycle-based** and **monthly** pricing modes.

---

## Test Data Requirements
To simulate real-world variation, collect or synthesize a mix of NEM12 datasets:

### NEM12 Variations
| Category | Example | Purpose |
|-----------|----------|----------|
| **Single Import** | E1 only | Validate base flow handling |
| **Import + Export** | E1 + B1 | Check feed-in credit logic |
| **Controlled Load** | E1 + E2 | Validate multiple import flows |
| **Multiple NMIs** | 2+ NMIs | Validate grouping/aggregation |
| **Different Cadences** | 5, 15, 30 min | Verify cadence inference per (nmi, channel) and consistent totals |
| **Gaps or Duplicates** | Missing intervals | Validate data cleaning tolerance |
| **Timezones** | AEST, AEDT | Check DST and tz-aware logic |
| **Edge Months** | February, 31-day | Validate day-count calculations |

### Plan Variations
| Plan Type | Attributes | Validation Goal |
|------------|-------------|------------------|
| **Flat (All Times)** | One usage band | Verify simple usage calc |
| **TOU Plan** | Peak/Shoulder/Off-Peak | Validate time banding |
| **Demand Plan** | Demand window + kW charge | Check demand cost logic |
| **Feed-in Plan** | Solar export | Ensure credit application |
| **Discounted Plan** | Pay-on-time | Validate discount rounding |
| **GST On/Off** | Residential vs. exempt | Validate GST inclusion |

---

## Test Types

### 1. **Unit Tests**
Focus: Isolated validation of pure functions.
- `_label_cycles`: inclusive → exclusive boundaries, correct labels.
- `_cycle_billables`: correct kWh totals for import/export.
- TOU binning: aggregated kWh equals original sum.
- Demand window detection per cycle.

### 2. **Golden Reference Tests**
Focus: End-to-end accuracy against known bills.
Each dataset should have a matching **golden JSON** containing expected itemised results.

Example format:
```yaml
period: { start: 2025-07-01, end: 2025-07-30 }
expected:
  energy_cost: 316.17
  fixed_cost: 51.17
  demand_cost: 0.00
  feed_in_credit: -28.53
  pay_on_time_discount: -25.71
  gst: 34.17
  total: 347.28
plan:
  usage_bands:
    - name: all_times
      start: "00:00"
      end: "24:00"
      rate_c_per_kwh: 43.25
  fixed_c_per_day: 170.56
  feed_in_c_per_kwh: 60.0
  demand: null
```

The test will assert all monetary values within **±$0.02** of expected.

### 3. **Property-Based Tests**
Focus: Mathematical and logical invariants.
- Scaling test: doubling kWh doubles energy_cost.
- Additivity: two half-cycles = one full cycle.
- Rounding stability: repeated re-runs yield identical totals.

### 4. **Performance & Robustness Tests**
Focus: Large dataset performance and missing data tolerance.
- 1-year NEM12 file with 5-min cadence (100k+ rows).
- Missing day interpolation handling.
- Cycles spanning DST boundaries (Sydney zone).

---

## Test Automation Design
Use **pytest** for structured testing with parametrised cases.

Example:
```python
import meterdatalogic as ml
import meterdatalogic.types as mdtypes

@pytest.mark.parametrize("case", ["flat_alltimes_pv_jul2025", "tou_peak_shoulder"])
def test_bill_against_golden(case, load_case):
  df, meta = load_case(case)
  plan = mdtypes.Plan(
    usage_bands=[mdtypes.ToUBand(**b) for b in meta["plan"]["usage_bands"]],
    fixed_c_per_day=meta["plan"]["fixed_c_per_day"],
    feed_in_c_per_kwh=meta["plan"]["feed_in_c_per_kwh"],
    demand=(mdtypes.DemandCharge(**meta["plan"]["demand"]) if meta["plan"].get("demand") else None),
  )
  cycles = [(meta["period"]["start"], meta["period"]["end"])]
  bill = ml.pricing.compute_billables(df, plan, mode="cycles", cycles=cycles)
  out = ml.pricing.estimate_costs(
    bill,
    plan,
    include_gst=True,
    pay_on_time_discount=0.07,
  )
  row = out.iloc[0]
  for key, expected in meta["expected"].items():
    assert abs(float(row[key]) - float(expected)) <= 0.02
```

---

## Acceptance Criteria
| Category | Pass Criteria |
|-----------|----------------|
| **Accuracy** | All itemised fields within ±$0.02 of expected |
| **Date Logic** | Inclusive end date reflects retailer bill period |
| **GST/Discount Logic** | Matches bill ordering and rounding |
| **TOU & Demand Logic** | Matches per-band or per-window expectations |
| **Performance** | <1s for 100k intervals, <10s for 1M |
| **Idempotence** | Re-running yields identical results |