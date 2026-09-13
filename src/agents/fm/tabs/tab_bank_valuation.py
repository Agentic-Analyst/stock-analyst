"""User-facing justified-P/B workbook tab for balance-sheet financials."""

from __future__ import annotations

from typing import Any, Dict

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet


_CURRENCY_PREFIX = {
    "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥",
    "HKD": "HK$", "SGD": "S$", "AUD": "A$", "CAD": "C$",
    "CHF": "CHF ", "INR": "₹", "KRW": "₩", "TWD": "NT$",
}


def currency_number_format(currency: str, *, decimals: int = 2) -> str:
    prefix = _CURRENCY_PREFIX.get(str(currency or "").upper(), f"{currency} ")
    zeros = "0" if decimals <= 0 else "0." + "0" * decimals
    escaped = prefix.replace('"', '""')
    return f'"{escaped}"#,##{zeros}'


class BankValuationTabBuilder:
    """Build the model users should actually inspect for a bank/lender."""

    def __init__(self, valuation: Dict[str, Any], financial_data: Dict[str, Any]):
        self.valuation = valuation or {}
        self.financial_data = financial_data or {}
        company = self.financial_data.get("company_data") or {}
        basic = company.get("basic_info") or {}
        self.currency = basic.get("currency") or "USD"
        self.price_format = currency_number_format(self.currency)

    def create_tab(self, workbook: openpyxl.Workbook) -> Worksheet:
        if "Bank Valuation" in workbook.sheetnames:
            workbook.remove(workbook["Bank Valuation"])
        summary_index = (
            workbook.sheetnames.index("Summary")
            if "Summary" in workbook.sheetnames else len(workbook.sheetnames)
        )
        ws = workbook.create_sheet("Bank Valuation", summary_index)
        inputs = self.valuation.get("bank_inputs") or {}
        company = self.financial_data.get("company_data") or {}
        market = company.get("market_data") or {}
        guidance = company.get("forward_guidance") or {}
        consensus = company.get("analyst_consensus") or {}
        recommendation = consensus.get("recommendation") or {}

        ws["A1"] = "BANK VALUATION — JUSTIFIED P/B AND ROE-ADJUSTED PEERS"
        ws["A1"].font = Font(bold=True, size=14)
        ws.merge_cells("A1:F1")
        ws["A2"] = (
            "Corporate free-cash-flow DCF is not applicable to this balance-sheet "
            "business. Deposit, loan, and investment flows are financing activity, "
            "not ordinary corporate reinvestment."
        )
        ws.merge_cells("A2:F2")
        ws["A2"].alignment = Alignment(wrap_text=True)

        rows = [
            (4, "Current market price", market.get("current_price"), self.price_format,
             "Provider quote at analysis time"),
            (5, "Common book value per share", inputs.get("bvps"), self.price_format,
             inputs.get("book_value_per_share_source")),
            (6, "Sustainable common ROE", inputs.get("roe"), "0.0%",
             inputs.get("return_on_equity_source")),
            (7, "Cost of equity", inputs.get("cost_of_equity"), "0.00%",
             inputs.get("cost_of_equity_source")),
            (8, "Long-run growth", inputs.get("terminal_growth"), "0.00%",
             "Bounded long-run nominal growth assumption"),
        ]
        for row, label, value, number_format, source in rows:
            ws.cell(row=row, column=1, value=label)
            ws.cell(row=row, column=2, value=value)
            ws.cell(row=row, column=2).number_format = number_format
            ws.cell(row=row, column=4, value=source or "source unavailable")

        ws["A10"] = "Raw justified P/B = (ROE - g) / (cost of equity - g)"
        ws["B10"] = "=(B6-B8)/(B7-B8)"
        ws["B10"].number_format = '0.00"x"'
        ws["A11"] = "Bounded justified P/B"
        ws["B11"] = "=MAX(0.4,MIN(3,B10))"
        ws["B11"].number_format = '0.00"x"'
        ws["D11"] = (
            "Safety band 0.4x–3.0x; any active clamp blocks point publication"
        )
        ws["A12"] = "Normalized-ROE justified P/B value per share"
        ws["B12"] = "=ROUND(B5*B11,2)"
        ws["B12"].number_format = self.price_format

        ws["A14"] = "ROE-adjusted peer-implied P/B"
        peer_pb = inputs.get("peer_implied_price_to_book")
        ws["B14"] = peer_pb
        ws["B14"].number_format = '0.00"x"'
        ws["D14"] = inputs.get("peer_method") or "No eligible peer method"
        ws["A15"] = "ROE-adjusted peer value per share"
        ws["B15"] = "=ROUND(B5*B14,2)" if peer_pb else None
        ws["B15"].number_format = self.price_format
        ws["A16"] = "Eligible peer observations"
        ws["B16"] = inputs.get("peer_observation_count") or 0
        ws["B16"].number_format = "0"

        forward_value = self.valuation.get("forward_consensus_fair_value")
        ws["A17"] = "Forward-consensus ROE scenario value"
        ws["B17"] = forward_value
        ws["B17"].number_format = self.price_format
        ws["D17"] = inputs.get("forward_consensus_roe_source") or (
            inputs.get("forward_consensus_roe_reason") or "No eligible forward-ROE scenario"
        )

        peer_value = self.valuation.get("peer_fair_value")
        ws["A18"] = "Valuation audit composite"
        supported_cells = ["B12"]
        if peer_value:
            supported_cells.append("B15")
        if forward_value:
            supported_cells.append("B17")
        ws["B18"] = (
            f"=ROUND(AVERAGE({','.join(supported_cells)}),2)"
            if len(supported_cells) > 1 else "=B12"
        )
        ws["B18"].number_format = self.price_format
        ws["B18"].font = Font(bold=True, size=12)
        ws["B18"].fill = PatternFill("solid", fgColor="FFD966")
        ws["A19"] = "Method range low"
        ws["B19"] = (
            f"=MIN({','.join(supported_cells)})"
            if len(supported_cells) > 1 else "=B12"
        )
        ws["B19"].number_format = self.price_format
        ws["A20"] = "Method range high"
        ws["B20"] = (
            f"=MAX({','.join(supported_cells)})"
            if len(supported_cells) > 1 else "=B12"
        )
        ws["B20"].number_format = self.price_format
        ws["A21"] = "Midpoint upside / (downside)"
        ws["B21"] = '=IFERROR(B18/B4-1,"")'
        ws["B21"].number_format = "0.0%"
        ws["A22"] = "Publication status"
        ws["B22"] = (
            "WITHHELD — scenario range only"
            if self.valuation.get("point_estimate_withheld")
            else "PUBLISHABLE"
        )
        ws["A23"] = "Publication reason"
        ws["B23"] = self.valuation.get("publication_withheld_reason") or (
            "The deterministic bank-method publication checks passed."
        )
        ws.merge_cells("B23:D23")
        ws["B23"].alignment = Alignment(wrap_text=True, vertical="top")

        ws["A25"] = "External analyst benchmark (not intrinsic value)"
        ws["A25"].font = Font(bold=True)
        ws["A26"] = "Mean analyst target"
        ws["B26"] = guidance.get("target_mean_price")
        ws["B26"].number_format = self.price_format
        ws["A27"] = "Target analyst count"
        ws["B27"] = guidance.get("number_of_analyst_opinions") or 0
        ws["A28"] = "Recommendation consensus"
        ws["B28"] = recommendation.get("label") or "unavailable"
        ws["D26"] = ((consensus.get("price_target") or {}).get("source") or
                     "source unavailable")
        ws["C28"] = recommendation.get("source") or "source unavailable"
        ws["D25"] = "Forward EPS benchmark used in bank scenario"
        ws["D25"].font = Font(bold=True)
        ws["D26"] = "Consensus-implied common ROE"
        ws["E26"] = inputs.get("forward_consensus_roe")
        ws["E26"].number_format = "0.0%"
        ws["D27"] = "Forward justified P/B"
        ws["E27"] = inputs.get("forward_consensus_justified_pb")
        ws["E27"].number_format = '0.00"x"'
        ws["D28"] = "Qualified EPS horizons"
        ws["E28"] = len(inputs.get("forward_consensus_roe_observations") or [])
        ws["D29"] = "Peer-comparison subject TTM ROE"
        ws["E29"] = inputs.get("peer_subject_return_on_equity")
        ws["E29"].number_format = "0.0%"
        ws["F29"] = inputs.get("peer_subject_return_on_equity_source")

        peer = ((self.financial_data.get("industry_data") or {}).get("peer_comps") or {})
        observations = [row for row in peer.get("observations") or [] if isinstance(row, dict)]
        if observations:
            start = 31
            headers = (
                "Peer", "P/B", "Trailing common ROE", "P/B ÷ (ROE - g)",
                "Subject-ROE implied P/B", "Market cap (USD mm)",
            )
            for column, header in enumerate(headers, 1):
                ws.cell(row=start, column=column, value=header).font = Font(bold=True)
            for offset, observation in enumerate(observations, 1):
                row = start + offset
                ws.cell(row=row, column=1, value=observation.get("symbol"))
                ws.cell(row=row, column=2, value=observation.get("price_to_book"))
                ws.cell(row=row, column=2).number_format = '0.00"x"'
                roe_pct = observation.get("return_on_equity_ttm_pct")
                ws.cell(row=row, column=3, value=(roe_pct / 100.0 if isinstance(
                    roe_pct, (int, float)) else None))
                ws.cell(row=row, column=3).number_format = "0.0%"
                ws.cell(row=row, column=4, value=f'=IFERROR(B{row}/(C{row}-$B$8),"")')
                ws.cell(row=row, column=4).number_format = '0.00"x"'
                ws.cell(row=row, column=5, value=f'=IFERROR(D{row}*($E$29-$B$8),"")')
                ws.cell(row=row, column=5).number_format = '0.00"x"'
                ws.cell(row=row, column=6, value=observation.get(
                    "market_cap_usd_millions"))
                ws.cell(row=row, column=6).number_format = '#,##0'

        for cell in ("A12", "A17", "A18", "A22"):
            ws[cell].font = Font(bold=True)
        for column, width in {
            "A": 43, "B": 24, "C": 24, "D": 24, "E": 27, "F": 24,
        }.items():
            ws.column_dimensions[column].width = width
        ws.freeze_panes = "A4"
        ws.sheet_view.showGridLines = False
        return ws


def apply_bank_summary(workbook: openpyxl.Workbook) -> Worksheet:
    """Replace the generic DCF dashboard with bank-method references.

    This is a clean method-specific surface, not a relabelled industrial DCF.
    Leaving the old formulas below overwritten headline rows caused hidden DCF
    errors to fail the entire bank artifact and exposed irrelevant metrics to
    spreadsheet users who unhid rows or sheets.
    """
    ws = workbook["Summary"]
    ws.delete_rows(1, ws.max_row)
    bank = "'Bank Valuation'"
    ws["A1"] = "SUMMARY — BALANCE-SHEET FINANCIAL VALUATION"
    ws["A2"] = (
        "Industrial free-cash-flow DCF is not applicable. See Bank Valuation "
        "for sourced inputs, peer observations, and the publication decision."
    )
    ws["A3"], ws["B3"] = "Publication status", f"={bank}!B22"
    ws["A4"], ws["B4"] = "Cost of equity", f"={bank}!B7"
    ws["A5"], ws["B5"] = "Long-run growth", f"={bank}!B8"
    ws["A6"], ws["B6"] = "Sustainable common ROE", f"={bank}!B6"
    ws["A7"], ws["B7"] = "Justified P/B", f"={bank}!B11"
    ws["A8"], ws["B8"] = "Forward-consensus ROE scenario", f"={bank}!B17"
    ws["A9"], ws["B9"] = "Current Market Price", f"={bank}!B4"
    ws["A13"], ws["B13"] = "Primary valuation method", "Justified P/B x normalized ROE"
    ws["A14"], ws["B14"] = "Common book value per share", f"={bank}!B5"
    ws["A15"], ws["B15"] = "Sustainable common ROE", f"={bank}!B6"
    ws["A16"], ws["B16"] = "Cost of equity", f"={bank}!B7"
    ws["A17"], ws["B17"] = "External benchmark role", "Publication cross-check only"
    ws["A18"], ws["B18"] = "Value per Share (Justified P/B)", f"={bank}!B12"
    ws["A19"], ws["B19"] = "Value per Share (Forward-Consensus ROE)", f"={bank}!B17"
    ws["A20"], ws["B20"] = "Peer valuation method", "ROE-adjusted same-subindustry P/B"
    ws["A21"], ws["B21"] = "Peer observations", f"={bank}!B16"
    ws["A22"], ws["B22"] = "Value per Share (ROE-Adjusted Peer P/B)", f"={bank}!B15"
    ws["A26"], ws["B26"] = "Bank Valuation Audit Composite", f"={bank}!B18"
    ws["A27"], ws["B27"] = "Upside vs Market", f"={bank}!B21"
    ws["A28"], ws["B28"] = "Scenario Range Spread", f"=IFERROR({bank}!B20/{bank}!B19-1,0)"
    ws["A30"], ws["B30"] = "ROE-Adjusted Peer P/B Cross-Check", f"={bank}!B15"
    ws["A31"], ws["B31"] = "Analyst Consensus Target (reference)", f"={bank}!B26"
    ws["A33"], ws["B33"] = "Common BVPS", f"={bank}!B5"
    ws["A34"], ws["B34"] = "Normalized common ROE", f"={bank}!B6"
    ws["A35"], ws["B35"] = "Cost of equity", f"={bank}!B7"
    ws["A36"], ws["B36"] = "Justified P/B", f"={bank}!B11"
    ws["A37"], ws["B37"] = "ROE-Adjusted Peer P/B", f"={bank}!B14"
    ws["A38"], ws["B38"] = "Long-run growth", f"={bank}!B8"
    ws["A39"], ws["B39"] = "Midpoint vs market", f"={bank}!B21"
    ws["A41"] = "Corporate DCF, reverse DCF, and FCF sensitivity"
    ws["B41"] = "NOT APPLICABLE TO BALANCE-SHEET FINANCIALS"
    for column, width in {"A": 46, "B": 32, "C": 18, "D": 24}.items():
        ws.column_dimensions[column].width = width
    ws.freeze_panes = "A3"
    ws.sheet_view.showGridLines = False
    return ws
