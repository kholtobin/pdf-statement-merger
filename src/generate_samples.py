"""
Generate 12 synthetic monthly statements as PDFs.

Each quarter uses a different layout convention — ISO vs. slashed vs. written
dates, and minus-sign vs. parenthesised debits — so the extractor has realistic
inconsistency to normalise. All data is fake.

    python src/generate_samples.py
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# description -> category, typical amount range, is_income
VENDORS = [
    ("Acme Cloud Hosting", "Software", (180, 420), False),
    ("Fig Design SaaS subscription", "Software", (39, 89), False),
    ("Repo CI minutes", "Software", (25, 140), False),
    ("Payroll - engineering", "Payroll", (7800, 9200), False),
    ("Payroll - contractors", "Payroll", (1800, 3400), False),
    ("Coworking desk rental", "Office", (300, 450), False),
    ("Office supplies", "Office", (35, 180), False),
    ("Flight - client visit", "Travel", (210, 640), False),
    ("Hotel - conference", "Travel", (150, 480), False),
    ("Ads campaign", "Marketing", (400, 1500), False),
    ("Newsletter platform", "Marketing", (49, 120), False),
    ("Account maintenance fee", "Bank Fees", (12, 28), False),
    ("Wire transfer fee", "Bank Fees", (8, 35), False),
    ("Client payment - Northwind", "Income", (4200, 9800), True),
    ("Client payment - Globex", "Income", (3100, 7600), True),
    ("Client payment - Initech", "Income", (2500, 6400), True),
]


def fmt_date(d: date, style: int) -> str:
    if style == 0:
        return d.isoformat()                      # 2026-01-05
    if style == 1:
        return d.strftime("%d/%m/%Y")             # 05/01/2026
    return d.strftime("%b %-d, %Y")               # Jan 5, 2026


def fmt_amount(value: float, style: int) -> str:
    """style 0/2 -> -1,234.56 ; style 1 -> (1,234.56) for debits."""
    if value < 0 and style == 1:
        return f"({abs(value):,.2f})"
    return f"{value:,.2f}" if value >= 0 else f"-{abs(value):,.2f}"


def build_month(month_idx: int, out_dir: Path, rng: random.Random) -> None:
    year = 2026
    style = month_idx // 4  # 0, 1, 2 -> three different conventions
    month_name = MONTHS[month_idx]

    n_tx = rng.randint(9, 14)
    rows = []
    for _ in range(n_tx):
        desc, cat, (lo, hi), is_income = rng.choice(VENDORS)
        amount = round(rng.uniform(lo, hi), 2)
        if not is_income:
            amount = -amount
        day = rng.randint(1, 28)
        rows.append((date(year, month_idx + 1, day), desc, amount))
    rows.sort(key=lambda r: r[0])

    styles = getSampleStyleSheet()
    h_style = ParagraphStyle("h", parent=styles["Title"], fontSize=18, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=10)

    path = out_dir / f"statement_{year}_{month_idx + 1:02d}.pdf"
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, topMargin=22 * mm, leftMargin=20 * mm, rightMargin=20 * mm
    )

    story = [
        Paragraph("Meridian Business Bank", h_style),
        Paragraph("Monthly Account Statement", styles["Heading3"]),
        Spacer(1, 4 * mm),
        Paragraph("Account: **** 4417 — Acme Retail Ltd.", small),
        Paragraph(f"Period: {month_name} {year}", small),
        Spacer(1, 7 * mm),
    ]

    table_rows = [["Date", "Description", "Amount"]]
    for d, desc, amount in rows:
        table_rows.append([fmt_date(d, style), desc, fmt_amount(amount, style)])

    table = Table(table_rows, colWidths=[32 * mm, 100 * mm, 33 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
            ]
        )
    )
    story += [table, Spacer(1, 6 * mm)]

    total = round(sum(r[2] for r in rows), 2)
    closing = Table(
        [["Net movement for period", fmt_amount(total, style)]],
        colWidths=[132 * mm, 33 * mm],
    )
    closing.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
            ]
        )
    )
    story.append(closing)

    doc.build(story)
    print(f"wrote samples/{path.name}  ({n_tx} transactions, style {style})")


def main() -> None:
    rng = random.Random(20260128)  # deterministic samples
    out_dir = Path(__file__).resolve().parent.parent / "samples"
    out_dir.mkdir(exist_ok=True)
    for i in range(12):
        build_month(i, out_dir, rng)


if __name__ == "__main__":
    main()
