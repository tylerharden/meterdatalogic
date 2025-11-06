# Meter Data File Structure & Format Considerations

## 1. Overview
Electricity meter data can arrive in a range of industry-standard and bespoke formats.  
For the *Meter Data Tool (MDT)*, we will primarily support:

| Format | Description | Typical Source |
|---------|--------------|----------------|
| **NEM12** | Standard CSV format defined by AEMO for interval (consumption/export) data. | Retailers, metering data providers, or MSATS extractions. |
| **CSV (Custom / Corporate Extracts)** | Site-specific or aggregated interval data exported from internal systems. | EQL internal teams, customers, or Energy Data Portal. |
| **NEM13** | Billing (accumulated) data format — not interval-based. | Out of scope for initial MVP, may be supported later for completeness. |
| **API / Database Query Results** | Interval or summary data retrieved via internal APIs or SQL interfaces. | Direct integration phase post-MVP. |

---

## 2. NEM12 File Structure (AEMO Standard)

A NEM12 file is a **flat text (CSV-like)** structure that can contain **multiple NMIs, meters, and channels** in one file.

### 2.1 Record types

| Record Type | Code | Purpose |
|--------------|------|----------|
| **100** | File Header | Metadata about sender, creation date, etc. |
| **200** | NMI Data Details | Identifies an NMI and associated meta (meter serials, suffixes, register IDs, UOM, interval length, etc.). |
| **300** | Interval Data | Actual meter readings (date, 48 values per day for 30-min cadence). |
| **400** | Quality Flags | Optional: per-interval data quality and substitution indicators. |
| **500** | Checksum | Optional end-of-file checksum validation. |

Example (simplified):

```
100,NEM12,20250501,AEMO,MDP01
200,NMI1234567,123456789,E1,KWH,30
300,2025/04/01,0.23,0.21,0.19,0.18,0.16,0.15,...,0.20,N
300,2025/04/02,0.22,0.20,0.18,...,0.19,N
200,NMI7654321,987654321,B1,KWH,30
300,2025/04/01,0.00,0.00,0.00,...,0.12,N
500,CheckSum
```

### 2.2 Hierarchy

```
File
 ├─ NMI #1
 │   ├─ Channel E1 (Import)
 │   ├─ Channel B1 (Export)
 │   └─ Channel E2 (Controlled Load)
 ├─ NMI #2
 │   └─ Channel E1 (Import)
 └─ NMI #3
     ├─ Meter Serial #1
     ├─ Meter Serial #2 (Replacement)
     └─ ...
```

Each (NMI, Channel, Meter Serial) group can have different:
- Start and end dates
- Interval cadences (15-, 30-, 60-min)
- Gaps or overlaps

---

## 3. Canonical Data Model

Once parsed, each NEM12 channel is normalized to the **canonical dataframe format** used throughout the MDT:

| Column | Type | Description |
|---------|------|-------------|
| `t_start` | datetime (tz-aware) | Start time of interval (local time). |
| `nmi` | string | National Meter Identifier. |
| `channel` | string | Raw suffix (E1, E2, B1, etc.). |
| `flow` | string | Semantic flow classification (`grid_import`, `grid_export_solar`, etc.). |
| `kwh` | float | Energy for that interval. |
| `cadence_min` | int | Interval length (e.g., 15, 30, 60). |
| `meter_serial` | string | Meter serial (if available). |
| `quality_flag` | string | (Optional) AEMO data quality code. |

---

## 4. Multi-NMI & Multi-Meter Considerations

| Category | Issue | Required Handling |
|-----------|-------|-------------------|
| **Multiple NMIs** | A single NEM12 file can contain many NMIs. | **User must select one NMI** before proceeding to analysis. We will display a list of NMIs detected and their available channels/date ranges. |
| **Multiple Meters per NMI** | Meter replacements can cause overlapping or disjoint periods. | Merge chronologically; flag overlaps. Prefer later meter if overlapping. |
| **Multiple Channels per Meter** | E1/E2 (import) and B1 (export) are common. | Each becomes a distinct `flow`. Combine in summaries. |
| **Different Cadences** | Some 15-min, others 30-min. | Resample to user-chosen canonical cadence (default 30-min). |
| **Disjoint Time Periods** | Some channels may start or stop mid-year. | Summaries should respect individual time spans. |
| **Mixed timezones** | Older files may be UTC or unspecified. | Infer from header or assume QLD (AEST, UTC+10) — enforce tz-aware index. |
| **Quality Flags (N, S, E)** | Indicate normal/substituted/estimated data. | Store as metadata; optional filters for “verified only.” |

---

## 5. Other Data Formats to Support

### 5.1 Custom CSV (Corporate / Customer Extracts)
Typical columns:
```
DateTime, SiteID, kWh, FlowType, Channel
```
- Often already aggregated or averaged.
- Must detect cadence, timezone, and flow semantics.
- May represent multiple NMIs (“SiteID”) — same user selection logic applies.

### 5.2 API / Database Integration (future)
Internal APIs or direct SQL extracts (e.g., ActiveDash, EMP, InfoDynamics) may return:
```
timestamp | nmi | register_id | import_kwh | export_kwh | quality | source
```
These will be mapped to the canonical structure via lightweight adapters.

---

## 6. Data Validation Rules

| Check | Description | Enforcement |
|--------|--------------|-------------|
| **Regular cadence** | All intervals must align to consistent cadence (15/30/60). | Reindex or flag if irregular. |
| **Monotonic timeline** | Timestamps must increase without duplication. | Sort & deduplicate. |
| **No negative kWh** | Interval energy cannot be < 0. | Clamp or warn. |
| **Reasonable magnitude** | >5 kWh/30 min flags potential cumulative data. | Warn user. |
| **Timezone aware** | All timestamps must include tz info (AEST). | Convert or raise error. |

---

## 7. File Selection Workflow

1. **Upload / Load file(s)**  
   - Detect format (NEM12, custom CSV, etc.).
2. **Parse header records**  
   - Extract NMIs, meters, channels, and date ranges.
3. **Display summary table**  
   Example:

   | NMI | Channels | Start | End | Cadence | Meters |
   |------|-----------|-------|-----|----------|---------|
   | 4001234567 | E1, B1 | 2024-01-01 | 2024-06-30 | 30 min | 123456789 |
   | 4007654321 | E1 | 2023-12-15 | 2024-04-01 | 15 min | 987654321 |

4. **User selects one NMI** to continue.  
   - Load corresponding (NMI, Channel) data into canonical dataframe.  
   - Store other NMIs as cached but inactive datasets.

---

## 8. Downstream Implications

| Area | Impact |
|------|--------|
| **Scenario modelling** | Must always operate on a *single NMI dataset*. |
| **Visualisations** | Average daily and monthly charts assume one continuous channel set. |
| **Tariff estimation** | Tariffs apply per NMI / connection point. |
| **Summaries** | Multi-NMI reports can be aggregated later, but not mixed during modelling. |

---

## 9. Future Enhancements

- **Automatic detection of cumulative vs interval data** (some legacy NMI data may contain cumulative meter reads).  
- **Meter-change reconciliation tool** (flag data gaps/overlaps, auto-select valid segments).  
- **Batch-mode processing** for portfolio-level analytics after single-NMI pipeline is proven.  
- **Integration with AEMO MDFF (Meter Data File Format) standard** once mandated (post-2026).  

---

## 10. Summary

**Key design principle:**  
> The Meter Data Tool will always model and visualise *one NMI at a time* to ensure correctness, clarity, and performance.

NEM12 and related formats are flexible but complex; clear pre-processing steps (parse → detect → user select → validate) will guarantee consistent behaviour across data sources.

