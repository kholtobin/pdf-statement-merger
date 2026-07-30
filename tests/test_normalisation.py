"""Unit tests for the pure normalisation helpers."""

from __future__ import annotations

import pytest

from merge_statements import (
    CATEGORY_RULES,
    DATE_FORMATS,
    _month_number,
    categorise,
    parse_amount,
    parse_date,
)


# --- parse_date -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-01-05", "2026-01-05"),          # ISO
        ("05/01/2026", "2026-01-05"),          # DD/MM/YYYY
        ("Jan 5, 2026", "2026-01-05"),         # abbreviated month
        ("January 5, 2026", "2026-01-05"),     # full month
        ("12/31/2026", "2026-12-31"),          # MM/DD/YYYY, unambiguous
        ("  2026-01-05  ", "2026-01-05"),      # surrounding whitespace
    ],
)
def test_parse_date_supported_formats(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "not a date", "2026-13-45", "5 Jan 26"])
def test_parse_date_rejects_unparsable(raw):
    assert parse_date(raw) is None


def test_parse_date_prefers_day_first_when_ambiguous():
    """05/01/2026 is read as 5 January, not 1 May.

    %d/%m/%Y sits ahead of %m/%d/%Y in DATE_FORMATS, so day-first wins. Pinned
    here so the tuple can't be reordered without a failing test.
    """
    assert DATE_FORMATS.index("%d/%m/%Y") < DATE_FORMATS.index("%m/%d/%Y")
    assert parse_date("05/01/2026") == "2026-01-05"


# --- parse_amount ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234.56", 1234.56),
        ("1234.56", 1234.56),
        ("-1,234.56", -1234.56),
        ("(1,234.56)", -1234.56),      # parenthesised debit
        ("(35.00)", -35.0),
        ("−1,234.56", -1234.56),  # unicode minus
        ("  1,234.56  ", 1234.56),
        ("0.00", 0.0),
    ],
)
def test_parse_amount_supported_formats(raw, expected):
    assert parse_amount(raw) == pytest.approx(expected)


def test_parse_amount_parenthesised_zero_stays_zero():
    assert parse_amount("(0.00)") == 0


@pytest.mark.parametrize("raw", ["", "   ", "n/a", "-", "1,234.56 USD"])
def test_parse_amount_rejects_unparsable(raw):
    assert parse_amount(raw) is None


# --- categorise -----------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Payroll - engineering", "Payroll"),
        ("Payroll - contractors", "Payroll"),
        ("Acme Cloud Hosting", "Software"),
        ("Fig Design SaaS subscription", "Software"),
        ("Repo CI minutes", "Software"),
        ("Coworking desk rental", "Office"),
        ("Office supplies", "Office"),
        ("Flight - client visit", "Travel"),
        ("Hotel - conference", "Travel"),
        ("Ads campaign", "Marketing"),
        ("Newsletter platform", "Marketing"),
        ("Account maintenance fee", "Bank Fees"),
        ("Wire transfer fee", "Bank Fees"),
        ("Client payment - Northwind", "Income"),
        ("Something entirely unknown", "Uncategorised"),
    ],
)
def test_categorise(description, expected):
    assert categorise(description) == expected


def test_categorise_is_case_insensitive():
    assert categorise("PAYROLL - ENGINEERING") == "Payroll"
    assert categorise("acme CLOUD hosting") == "Software"


def test_categorise_uses_first_matching_rule():
    """A description hitting two rule groups takes the earlier one."""
    # "contractor" -> Payroll (rule 0), "invoice paid" -> Income (rule 6)
    assert categorise("Contractor invoice paid") == "Payroll"
    assert [c for _, c in CATEGORY_RULES].index("Payroll") < [
        c for _, c in CATEGORY_RULES
    ].index("Income")


# --- _month_number --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [("January", 1), ("Jan", 1), ("December", 12), ("Dec", 12), ("Fizzbuzz", 0), ("", 0)],
)
def test_month_number(name, expected):
    assert _month_number(name) == expected
