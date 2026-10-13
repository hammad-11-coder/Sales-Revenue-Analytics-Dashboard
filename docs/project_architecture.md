# Project architecture and workflow

All data is **synthetic**. The project is an end-to-end pipeline from generated transactions to an interactive dashboard. Each stage produces files and is validated before the next stage uses it.

```
 generate_data.py ──► data/raw/*.csv  (+ defect_manifest.json)
                           │
                    clean_data.py  (rules O*, I*, C*, P*, R*; log + quarantine)
                           │
                           ▼
                  data/processed/*.csv ──► validate_data.py (78 checks)
                           │
        ┌──────────────────┼───────────────────────┬──────────────────────┐
        ▼                  ▼                       ▼                      ▼
  MySQL 8.0           Power BI Desktop        Python / pandas        Streamlit app
  sql/01..04          powerbi/ (model,        kpi_definitions.py     streamlit_app/
  (schema, DQ,        DAX, build guide,       notebook, tests        (optional,
  views, analysis)    reference values)                              no Power BI needed)
        │                  │                       │                      │
        └───────────── same KPI definitions (docs/business_rules.md) ─────┘
                           │
        verify_sql_against_python.py: 52 SQL results == independent pandas results
```

## Stages and the six "agents"

The brief asks for six specialised roles. They were run sequentially, each producing files and a validation result before the next began.

| # | Role | Output | Validation produced |
|---|---|---|---|
| 1 | Data engineering | `generate_data.py`, `clean_data.py`, `validate_data.py`, `data/` | 78 checks, including "every injected defect found exactly once" |
| 2 | SQL analyst | `sql/01`–`04`, `verify_sql_against_python.py` | 52 SQL-vs-pandas checks (SQLite engine; MySQL DDL not executed) |
| 3 | Analytics engineering | `kpi_definitions.py`, `docs/business_rules.md` | unit tests for KPI logic, comparison periods, edge cases |
| 4 | Power BI developer | `powerbi/` (DAX, model, theme, build guide), reference values | **not executed** (no Power BI Desktop); reference values supplied for manual checking |
| 5 | QA and validation | `tests/` (100 pytest tests), independent review | see README "Quality assurance performed"; the review found and fixed an empty-selection "−100 %" bug in the growth logic |
| 6 | Documentation and portfolio | README, `docs/`, data dictionary, preview image | consistency check: README figures are regenerated from the data by `generate_insights.py` |

## Design decisions

- **One definition of every KPI.** `python/kpi_definitions.py` is the reference; SQL, DAX and the Streamlit app are written to match it and are tested against it (DAX by hand).
- **Defects with a known answer.** The raw data contains injected defects at recorded rates. This makes the cleaning logic testable: a rule that finds the wrong count fails the build.
- **Nothing is silently dropped.** Duplicates are counted; repairs are counted; rejected rows are quarantined with the rule id and the raw record.
- **Star schema.** One fact table at order-line grain, four dimensions, single-direction one-to-many relationships; header-level facts (orders, customers, AOV) are distinct counts so the line grain cannot inflate them.
- **Calendar-driven time intelligence.** A continuous `DimDate` (and the `vw_monthly_summary` view) guarantees no missing months and makes previous-period logic explicit and testable.
- **Portable SQL subset.** Files 02–04 use only constructs common to MySQL 8.0 and SQLite, so they could be executed here. Only `01_create_schema.sql` (DDL, constraints, `LOAD DATA`) is MySQL-specific.
- **Honest scope.** A `.pbix` is not shipped because none can be authored in this environment; a build guide, tested-logic DAX and reference values are shipped instead (see README, "Known limitations").

## Repository map

| Path | Purpose |
|---|---|
| `data/raw`, `data/processed` | generated source data and cleaned analysis tables |
| `excel/` | Excel inspection and cleaning guide |
| `sql/` | MySQL schema and loading, quality checks, views, analysis queries |
| `python/` | generation, cleaning, validation, KPI logic, SQL verification, insights, preview renderer, notebook |
| `powerbi/` | DAX measures, data model, theme, build guide |
| `streamlit_app/` | optional interactive dashboard |
| `tests/` | pytest suite |
| `docs/` | business rules, data dictionary, architecture, validation report, insights, Power BI reference values |
| `dashboard_screenshots/` | layout preview (matplotlib); replace with Power BI screenshots after building |
