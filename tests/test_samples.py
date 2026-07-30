"""Integration tests against the 12 static statement PDFs in tests/fixtures/.

Read-only: the fixtures are opened, never written.
"""

from __future__ import annotations

import re

import pytest

from conftest import (
    EXPECTED,
    ISO_MONTHS,
    PARENTHESISED_MONTHS,
    TOTAL_TRANSACTIONS,
    WRITTEN_DATE_MONTHS,
)
from merge_statements import CATEGORY_RULES

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KNOWN_CATEGORIES = {category for _, category in CATEGORY_RULES} | {"Uncategorised"}


@pytest.mark.parametrize(("stem", "expected"), sorted(EXPECTED.items()))
def test_each_statement_parses_as_expected(parsed_by_stem, stem, expected):
    period, tx_count, net = expected
    st = parsed_by_stem[stem]

    assert st.period == period
    assert len(st.transactions) == tx_count
    assert st.computed_net == pytest.approx(net, abs=0.01)
    assert st.warnings == []


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_each_statement_reconciles(parsed_by_stem, stem):
    st = parsed_by_stem[stem]
    assert st.stated_net is not None
    assert st.reconciled is True, (
        f"{stem}: computed {st.computed_net} vs stated {st.stated_net}"
    )


def test_the_whole_folder_is_parsed_in_one_pass(parsed_statements):
    assert len(parsed_statements) == 12
    assert sum(len(st.transactions) for st in parsed_statements) == TOTAL_TRANSACTIONS


# --- normalisation across the three layout conventions --------------------


@pytest.mark.parametrize(
    "stems",
    [ISO_MONTHS, PARENTHESISED_MONTHS, WRITTEN_DATE_MONTHS],
    ids=["iso-dates", "slashed-dates", "written-dates"],
)
def test_dates_are_normalised_to_iso_whatever_the_source_format(parsed_by_stem, stems):
    for stem in stems:
        st = parsed_by_stem[stem]
        for t in st.transactions:
            assert ISO_DATE_RE.match(t["date"]), f"{stem}: {t['date']!r} is not ISO"
            assert t["date"].startswith(st.period), (
                f"{stem}: {t['date']} falls outside period {st.period}"
            )


def test_parenthesised_debits_become_negative_numbers(parsed_by_stem):
    """May–August print debits as (1,234.56); they must still be signed floats."""
    for stem in PARENTHESISED_MONTHS:
        st = parsed_by_stem[stem]
        debits = [t for t in st.transactions if t["category"] != "Income"]
        assert debits, f"{stem} has no debit rows to check"
        assert all(isinstance(t["amount"], float) for t in debits)
        assert all(t["amount"] < 0 for t in debits)


def test_income_rows_stay_positive(parsed_statements):
    income = [
        t for st in parsed_statements for t in st.transactions if t["category"] == "Income"
    ]
    assert income
    assert all(t["amount"] > 0 for t in income)


# --- categorisation -------------------------------------------------------


def test_every_transaction_gets_a_known_category(parsed_statements):
    categories = {t["category"] for st in parsed_statements for t in st.transactions}
    assert categories <= KNOWN_CATEGORIES


def test_no_sample_transaction_falls_through_to_uncategorised(parsed_statements):
    stragglers = [
        t["description"]
        for st in parsed_statements
        for t in st.transactions
        if t["category"] == "Uncategorised"
    ]
    assert stragglers == []
