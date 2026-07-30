"""Statement bookkeeping and the parse_statement branches the clean fixtures never hit.

These use the in-memory ``fake_pdf`` stub rather than a deliberately broken PDF —
no PDF is generated anywhere in this suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import transaction_table
from merge_statements import Statement, parse_statement

FAKE_PATH = Path("statement_2026_01.pdf")

HEADER_TEXT = "Meridian Business Bank\nPeriod: January 2026\n"


def statement(**kwargs) -> Statement:
    kwargs.setdefault("source_file", "statement_2026_01.pdf")
    return Statement(**kwargs)


def tx(amount: float) -> dict:
    return {
        "date": "2026-01-05",
        "description": "Office supplies",
        "amount": amount,
        "category": "Office",
    }


# --- Statement ------------------------------------------------------------


def test_computed_net_of_empty_statement_is_zero():
    assert statement().computed_net == 0


def test_computed_net_sums_and_rounds():
    """Float drift (0.1 + 0.2 == 0.30000000000000004) must not leak into totals."""
    st = statement(transactions=[tx(0.1), tx(0.2)])
    assert st.computed_net == 0.3


def test_not_reconciled_without_a_stated_net():
    st = statement(transactions=[tx(100.0)])
    assert st.stated_net is None
    assert st.reconciled is False


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        (100.00, True),    # exact
        (100.009, True),   # inside the 0.01 tolerance
        (100.02, False),   # outside it
        (-100.00, False),  # sign flip
    ],
)
def test_reconciliation_tolerance(stated, expected):
    st = statement(transactions=[tx(100.0)], stated_net=stated)
    assert st.reconciled is expected


# --- parse_statement ------------------------------------------------------


def test_parses_period_net_and_rows(fake_pdf):
    fake_pdf(
        text=HEADER_TEXT + "Net movement for period -120.50",
        tables=[
            transaction_table(
                ["2026-01-05", "Office supplies", "-45.50"],
                ["2026-01-09", "Account maintenance fee", "-75.00"],
            )
        ],
    )
    st = parse_statement(FAKE_PATH)

    assert st.source_file == "statement_2026_01.pdf"
    assert st.period == "2026-01"
    assert st.stated_net == pytest.approx(-120.50)
    assert st.computed_net == pytest.approx(-120.50)
    assert st.reconciled is True
    assert st.warnings == []
    assert st.transactions[0] == {
        "date": "2026-01-05",
        "description": "Office supplies",
        "amount": -45.50,
        "category": "Office",
    }


def test_parenthesised_stated_net_is_read_as_a_debit(fake_pdf):
    fake_pdf(
        text=HEADER_TEXT + "Net movement for period (1,234.56)",
        tables=[transaction_table(["2026-01-05", "Office supplies", "(1,234.56)"])],
    )
    st = parse_statement(FAKE_PATH)

    assert st.stated_net == pytest.approx(-1234.56)
    assert st.reconciled is True


def test_table_without_date_or_amount_header_is_ignored(fake_pdf):
    fake_pdf(
        text=HEADER_TEXT + "Net movement for period 0.00",
        tables=[
            transaction_table(
                ["Acme Retail Ltd.", "**** 4417"],
                header=["Account", "Number"],
            )
        ],
    )
    st = parse_statement(FAKE_PATH)

    assert st.transactions == []
    assert "no transactions extracted" in st.warnings


def test_unparsable_rows_are_reported_and_dropped(fake_pdf):
    fake_pdf(
        text=HEADER_TEXT + "Net movement for period -45.50",
        tables=[
            transaction_table(
                ["2026-01-05", "Office supplies", "-45.50"],
                ["not a date", "Office supplies", "-10.00"],
                ["2026-01-07", "Office supplies", "n/a"],
            )
        ],
    )
    st = parse_statement(FAKE_PATH)

    assert len(st.transactions) == 1
    unparsed = [w for w in st.warnings if w.startswith("unparsed row:")]
    assert len(unparsed) == 2
    assert "not a date" in unparsed[0]
    assert st.reconciled is True  # the surviving row still matches the stated net


def test_short_rows_are_skipped_without_crashing(fake_pdf):
    fake_pdf(
        text=HEADER_TEXT + "Net movement for period -45.50",
        tables=[
            transaction_table(
                ["2026-01-05", "Office supplies", "-45.50"],
                ["2026-01-06", "truncated row"],
            )
        ],
    )
    st = parse_statement(FAKE_PATH)

    assert len(st.transactions) == 1
    assert st.warnings == []


def test_empty_cells_are_tolerated(fake_pdf):
    """pdfplumber yields None for blank cells; they must not raise."""
    fake_pdf(
        text=HEADER_TEXT + "Net movement for period -45.50",
        tables=[
            transaction_table(
                ["2026-01-05", "Office supplies", "-45.50"],
                [None, None, None],
            )
        ],
    )
    st = parse_statement(FAKE_PATH)

    assert len(st.transactions) == 1
    assert any(w.startswith("unparsed row:") for w in st.warnings)


def test_missing_period_line_leaves_period_unset(fake_pdf):
    fake_pdf(
        text="Meridian Business Bank\nNet movement for period -45.50",
        tables=[transaction_table(["2026-01-05", "Office supplies", "-45.50"])],
    )
    st = parse_statement(FAKE_PATH)

    assert st.period is None


def test_missing_net_movement_is_warned(fake_pdf):
    fake_pdf(
        text=HEADER_TEXT,
        tables=[transaction_table(["2026-01-05", "Office supplies", "-45.50"])],
    )
    st = parse_statement(FAKE_PATH)

    assert st.stated_net is None
    assert st.reconciled is False
    assert "stated net movement not found" in st.warnings


def test_mismatched_net_is_flagged_not_absorbed(fake_pdf):
    fake_pdf(
        text=HEADER_TEXT + "Net movement for period -100.00",
        tables=[transaction_table(["2026-01-05", "Office supplies", "-45.50"])],
    )
    st = parse_statement(FAKE_PATH)

    assert st.reconciled is False
    assert st.warnings == [
        "does not reconcile: computed -45.50 vs stated -100.00"
    ]


def test_rows_from_every_page_are_collected(fake_pdf, monkeypatch):
    """A statement spanning two pages keeps both pages' transactions."""
    import merge_statements

    from conftest import _FakePage, _FakePDF

    pages = [
        _FakePage(
            HEADER_TEXT,
            [transaction_table(["2026-01-05", "Office supplies", "-45.50"])],
        ),
        _FakePage(
            "Net movement for period -120.50",
            [transaction_table(["2026-01-19", "Wire transfer fee", "-75.00"])],
        ),
    ]
    monkeypatch.setattr(
        merge_statements.pdfplumber, "open", lambda _path: _FakePDF(pages)
    )

    st = parse_statement(FAKE_PATH)

    assert len(st.transactions) == 2
    assert st.period == "2026-01"
    assert st.reconciled is True
