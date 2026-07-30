"""Shared fixtures.

The PDFs in ``tests/fixtures/`` are static copies of ``samples/``. Tests never
generate, rewrite or delete a PDF — they only read the committed ones, so a
regenerated ``samples/`` folder can never silently change what the suite asserts.

The few code paths that need a malformed statement (unparsable row, mismatched
net movement, missing period line) are driven by monkeypatching
``pdfplumber.open`` with an in-memory stub; no file is ever written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from merge_statements import Statement, parse_statement

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# file stem -> (period, transaction count, computed net)
EXPECTED: dict[str, tuple[str, int, float]] = {
    "statement_2026_01": ("2026-01", 14, 22340.64),
    "statement_2026_02": ("2026-02", 14, -15294.83),
    "statement_2026_03": ("2026-03", 9, 4183.27),
    "statement_2026_04": ("2026-04", 14, 26930.33),
    "statement_2026_05": ("2026-05", 10, -7104.67),
    "statement_2026_06": ("2026-06", 14, -3915.67),
    "statement_2026_07": ("2026-07", 14, -3654.12),
    "statement_2026_08": ("2026-08", 10, -9575.29),
    "statement_2026_09": ("2026-09", 11, 15722.33),
    "statement_2026_10": ("2026-10", 12, -10908.43),
    "statement_2026_11": ("2026-11", 11, -29363.41),
    "statement_2026_12": ("2026-12", 10, -1559.64),
}

TOTAL_TRANSACTIONS = sum(tx for _, tx, _ in EXPECTED.values())

# Which layout convention each month was written in, per generate_samples.py
# (style = month_idx // 4): ISO dates, DD/MM/YYYY with parenthesised debits,
# and written-out dates.
ISO_MONTHS = ("statement_2026_01", "statement_2026_02", "statement_2026_03", "statement_2026_04")
PARENTHESISED_MONTHS = ("statement_2026_05", "statement_2026_06", "statement_2026_07", "statement_2026_08")
WRITTEN_DATE_MONTHS = ("statement_2026_09", "statement_2026_10", "statement_2026_11", "statement_2026_12")


@pytest.fixture(scope="session")
def fixture_pdfs() -> list[Path]:
    """The 12 static statement PDFs, in filename order."""
    pdfs = sorted(FIXTURES_DIR.glob("*.pdf"))
    assert len(pdfs) == len(EXPECTED), (
        f"expected {len(EXPECTED)} fixture PDFs in {FIXTURES_DIR}, found {len(pdfs)}. "
        "Restore them with: cp samples/*.pdf tests/fixtures/"
    )
    return pdfs


@pytest.fixture(scope="session")
def parsed_statements(fixture_pdfs: list[Path]) -> list[Statement]:
    """Every fixture parsed once — PDF extraction is the slow part of the suite."""
    return [parse_statement(pdf) for pdf in fixture_pdfs]


@pytest.fixture(scope="session")
def parsed_by_stem(parsed_statements: list[Statement]) -> dict[str, Statement]:
    return {Path(st.source_file).stem: st for st in parsed_statements}


# --- in-memory stand-in for a PDF -----------------------------------------


class _FakePage:
    def __init__(self, text: str, tables: list[list[list[str]]]):
        self._text = text
        self._tables = tables

    def extract_text(self) -> str:
        return self._text

    def extract_tables(self) -> list[list[list[str]]]:
        return self._tables


class _FakePDF:
    def __init__(self, pages: list[_FakePage]):
        self.pages = pages

    def __enter__(self) -> _FakePDF:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def transaction_table(*rows: list[str], header: list[str] | None = None) -> list[list[str]]:
    """A pdfplumber-shaped table: header row followed by transaction rows."""
    return [header or ["Date", "Description", "Amount"], *rows]


@pytest.fixture
def fake_pdf(monkeypatch):
    """Return a factory that makes ``parse_statement`` read the given page content.

    Creates no files: it swaps out ``pdfplumber.open`` for a stub, which is the
    only way to exercise the malformed-statement branches without shipping a
    deliberately broken PDF.
    """

    def _install(text: str = "", tables: list[list[list[str]]] | None = None) -> None:
        page = _FakePage(text, list(tables or []))
        monkeypatch.setattr(
            "merge_statements.pdfplumber.open", lambda _path: _FakePDF([page])
        )

    return _install
