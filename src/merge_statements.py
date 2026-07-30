"""
Monthly PDF statements -> one reconciled Excel report.

Reads a folder of monthly statement PDFs, normalises inconsistent date and
amount formats, groups transactions into categories, and writes a single Excel
workbook with a summary sheet, a category breakdown and every transaction.

Usage:
    python src/merge_statements.py --input samples/ --output output/report.xlsx
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber

# --- Normalisation --------------------------------------------------------

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y")

PERIOD_RE = re.compile(r"period\s*:\s*([A-Za-z]+)\s+(\d{4})", re.IGNORECASE)
NET_RE = re.compile(
    r"net movement[^\d(\-]*(\(?-?[\d,]+\.\d{2}\)?)", re.IGNORECASE
)

# description keyword -> category
CATEGORY_RULES = [
    (("payroll", "salary", "contractor"), "Payroll"),
    (("hosting", "saas", "subscription", "ci minutes", "software"), "Software"),
    (("coworking", "office", "supplies", "rental"), "Office"),
    (("flight", "hotel", "travel", "conference"), "Travel"),
    (("ads", "campaign", "marketing", "newsletter"), "Marketing"),
    (("fee", "maintenance", "wire transfer"), "Bank Fees"),
    (("client payment", "invoice paid", "deposit"), "Income"),
]


def parse_date(value: str) -> str | None:
    """Normalise any supported date format to ISO (YYYY-MM-DD)."""
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_amount(value: str) -> float | None:
    """Normalise amounts: '1,234.56', '-1,234.56' and '(1,234.56)' (debit)."""
    value = value.strip()
    if not value:
        return None
    negative = value.startswith("(") and value.endswith(")")
    cleaned = value.strip("()").replace(",", "").replace("\u2212", "-")
    try:
        amount = float(cleaned)
    except ValueError:
        return None
    return -abs(amount) if negative else amount


def categorise(description: str) -> str:
    low = description.lower()
    for keywords, category in CATEGORY_RULES:
        if any(k in low for k in keywords):
            return category
    return "Uncategorised"


# --- Extraction -----------------------------------------------------------


@dataclass
class Statement:
    source_file: str
    period: str | None = None
    transactions: list[dict] = field(default_factory=list)
    stated_net: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def computed_net(self) -> float:
        return round(sum(t["amount"] for t in self.transactions), 2)

    @property
    def reconciled(self) -> bool:
        if self.stated_net is None:
            return False
        return abs(self.computed_net - self.stated_net) < 0.01


def parse_statement(pdf_path: Path) -> Statement:
    st = Statement(source_file=pdf_path.name)

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        tables = [t for page in pdf.pages for t in page.extract_tables()]

    if m := PERIOD_RE.search(text):
        st.period = f"{m.group(2)}-{_month_number(m.group(1)):02d}"
    if m := NET_RE.search(text):
        st.stated_net = parse_amount(m.group(1))

    for table in tables:
        header = [(c or "").strip().lower() for c in table[0]]
        if "date" not in header or "amount" not in header:
            continue
        d_i, a_i = header.index("date"), header.index("amount")
        # Some layouts omit the description column entirely.
        desc_i = header.index("description") if "description" in header else None
        needed = max(d_i, a_i, desc_i if desc_i is not None else 0)
        for row in table[1:]:
            cells = [(c or "").strip() for c in row]
            if len(cells) <= needed:
                continue
            iso = parse_date(cells[d_i])
            amount = parse_amount(cells[a_i])
            if iso is None or amount is None:
                st.warnings.append(f"unparsed row: {cells[:3]}")
                continue
            description = cells[desc_i] if desc_i is not None else ""
            st.transactions.append(
                {
                    "date": iso,
                    "description": description,
                    "amount": amount,
                    "category": categorise(description),
                }
            )

    if not st.transactions:
        st.warnings.append("no transactions extracted")
    if st.stated_net is None:
        st.warnings.append("stated net movement not found")
    elif not st.reconciled:
        st.warnings.append(
            f"does not reconcile: computed {st.computed_net:.2f} "
            f"vs stated {st.stated_net:.2f}"
        )
    return st


def _month_number(name: str) -> int:
    for fmt in ("%B", "%b"):
        try:
            return datetime.strptime(name, fmt).month
        except ValueError:
            continue
    return 0


# --- Reporting ------------------------------------------------------------

TRANSACTION_COLUMNS = [
    "Month",
    "Date",
    "Description",
    "Category",
    "Amount",
    "Source File",
]


def build_report(statements: list[Statement], out_path: Path) -> pd.DataFrame:
    # Named up front so a statement with no transactions still yields the full
    # set of columns instead of an empty frame the sort and pivot would reject.
    tx = pd.DataFrame(
        [
            {
                "Month": st.period,
                "Date": t["date"],
                "Description": t["description"],
                "Category": t["category"],
                "Amount": t["amount"],
                "Source File": st.source_file,
            }
            for st in statements
            for t in st.transactions
        ],
        columns=TRANSACTION_COLUMNS,
    ).sort_values(["Date", "Description"], ignore_index=True)

    summary = pd.DataFrame(
        [
            {
                "Month": st.period,
                "Transactions": len(st.transactions),
                "Inflows": round(
                    sum(t["amount"] for t in st.transactions if t["amount"] > 0), 2
                ),
                "Outflows": round(
                    sum(t["amount"] for t in st.transactions if t["amount"] < 0), 2
                ),
                "Net": st.computed_net,
                "Stated Net": st.stated_net,
                "Reconciled": "yes" if st.reconciled else "NO",
                "Notes": "; ".join(st.warnings),
            }
            for st in statements
        ]
    ).sort_values("Month", ignore_index=True)

    by_category = (
        tx.pivot_table(
            index="Category", columns="Month", values="Amount", aggfunc="sum"
        )
        .round(2)
        .fillna(0)
    )
    by_category["Total"] = by_category.sum(axis=1).round(2)
    by_category = by_category.sort_values("Total").reset_index()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        by_category.to_excel(writer, sheet_name="By Category", index=False)
        tx.to_excel(writer, sheet_name="Transactions", index=False)
        _format(writer)
    return summary


def _format(writer: pd.ExcelWriter) -> None:
    from openpyxl.styles import Font

    for ws in writer.book.worksheets:
        for col in ws.columns:
            width = max(
                (len(str(c.value)) for c in col if c.value is not None), default=8
            )
            ws.column_dimensions[col[0].column_letter].width = min(width + 2, 42)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Merge monthly PDF statements into Excel.")
    ap.add_argument("--input", "-i", required=True, help="Folder of statement PDFs")
    ap.add_argument("--output", "-o", default="output/report.xlsx")
    args = ap.parse_args(argv)

    folder = Path(args.input)
    pdfs = sorted(folder.glob("*.pdf")) if folder.is_dir() else [folder]
    if not pdfs:
        print(f"error: no PDFs found in {folder}", file=sys.stderr)
        return 1

    statements = []
    for pdf in pdfs:
        st = parse_statement(pdf)
        statements.append(st)
        flag = "" if st.reconciled else "  [check]"
        print(
            f"{pdf.name}: {len(st.transactions):>3} tx  net {st.computed_net:>11,.2f}{flag}"
        )

    build_report(statements, Path(args.output))
    total_tx = sum(len(s.transactions) for s in statements)
    unreconciled = [s for s in statements if not s.reconciled]
    print(f"\n{len(statements)} statements, {total_tx} transactions -> {args.output}")
    print(
        "All periods reconcile."
        if not unreconciled
        else f"{len(unreconciled)} period(s) need review."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
