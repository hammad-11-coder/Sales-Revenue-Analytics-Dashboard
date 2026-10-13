# Dashboard screenshots

| File | What it is |
|---|---|
| `dashboard_preview.png` | **Layout preview drawn with matplotlib** from the real processed data (Year = 2025 view). It follows the same 1280 × 720 grid as `powerbi/PowerBI_Build_Guide.md`. It is **not** a Power BI export or screenshot. |

After building the report in Power BI Desktop (see `powerbi/PowerBI_Build_Guide.md`), save real screenshots here as `powerbi_overview.png`, `powerbi_filtered.png`, etc., and point the README image at them. Regenerate the preview with:

```bash
python python/render_dashboard_preview.py            # Year = 2025
python python/render_dashboard_preview.py --year 0   # all 24 months
```

All data shown is synthetic.
