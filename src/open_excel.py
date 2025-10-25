import os, json, math, platform
from typing import Dict, Any, Optional

def _normalize_for_json(v):
    import datetime, decimal
    # Keep "" as "" (don't turn it into null), only None stays None
    if v is None:
        return None
    if isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v  # keep strings as-is

def _values_via_xlwings_portable(xlsx_path: str) -> Dict[str, Dict[str, Any]]:
    import xlwings as xw

    app = xw.App(visible=False, add_book=False)
    try:
        wb = xw.Book(xlsx_path)

        # Cross-platform calc settings
        # (no .api here; high-level works on both Mac and Windows)
        app.calculation = "automatic"
        app.display_alerts = False
        app.screen_updating = False

        # Refresh: high-level 'wb.api.RefreshAll()' often works, but is flaky on Mac.
        # We'll try it, but don't rely on it being present.
        try:
            wb.api.RefreshAll()
        except Exception:
            pass

        # Calculate everything (portable)
        # Do it twice to settle any volatile / data table dependencies
        app.calculate()
        app.calculate()

        # Save so cached values are up-to-date (also helps openpyxl fallback)
        wb.save()

        # Read values directly from live Excel via used_range
        result: Dict[str, Dict[str, Any]] = {}
        for sht in wb.sheets:
            try:
                ur = sht.used_range  # portable wrapper
                vals = ur.value
                # Ensure 2D list
                if vals is None:
                    result[sht.name] = {}
                    continue
                if not isinstance(vals, list) or (isinstance(vals, list) and (len(vals) == 0 or not isinstance(vals[0], list))):
                    vals = [[vals]]
                rows = len(vals)
                cols = max(len(r) if isinstance(r, list) else 1 for r in vals)
                sheet_map: Dict[str, Any] = {}
                for r in range(rows):
                    row_vals = vals[r] if isinstance(vals[r], list) else [vals[r]]
                    for c in range(cols):
                        v = row_vals[c] if c < len(row_vals) else None
                        sheet_map[f"({r+1},{c+1})"] = _normalize_for_json(v)
                result[sht.name] = sheet_map
            except Exception:
                # If anything odd, just return empty for that sheet
                result[sht.name] = {}
        return result
    finally:
        try:
            app.quit()
        except Exception:
            pass

def excel_to_json_values_portable(xlsx_path: str, out_json_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    # 1) Recalc & read via xlwings (portable)
    data = _values_via_xlwings_portable(xlsx_path)

    if out_json_path:
        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return data

