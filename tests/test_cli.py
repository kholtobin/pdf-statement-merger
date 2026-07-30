"""End-to-end runs of main(), driven against the static fixture PDFs."""

from __future__ import annotations

import pandas as pd

from conftest import EXPECTED, FIXTURES_DIR, TOTAL_TRANSACTIONS
from merge_statements import main


def test_folder_run_produces_a_report(tmp_path, capsys):
    out = tmp_path / "report.xlsx"
    code = main(["--input", str(FIXTURES_DIR), "--output", str(out)])

    assert code == 0
    assert out.exists()
    assert len(pd.read_excel(out, sheet_name="Transactions")) == TOTAL_TRANSACTIONS

    stdout = capsys.readouterr().out
    for stem in EXPECTED:
        assert f"{stem}.pdf:" in stdout
    assert f"12 statements, {TOTAL_TRANSACTIONS} transactions" in stdout
    assert "All periods reconcile." in stdout


def test_short_flags_work(tmp_path):
    out = tmp_path / "report.xlsx"
    assert main(["-i", str(FIXTURES_DIR), "-o", str(out)]) == 0
    assert out.exists()


def test_accepts_a_single_pdf_instead_of_a_folder(tmp_path, capsys):
    pdf = FIXTURES_DIR / "statement_2026_01.pdf"
    out = tmp_path / "one.xlsx"

    assert main(["--input", str(pdf), "--output", str(out)]) == 0

    summary = pd.read_excel(out, sheet_name="Summary")
    assert summary["Month"].tolist() == ["2026-01"]
    assert "statement_2026_01.pdf:" in capsys.readouterr().out


def test_empty_folder_exits_with_an_error(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()

    code = main(["--input", str(empty), "--output", str(tmp_path / "report.xlsx")])

    assert code == 1
    assert "no PDFs found" in capsys.readouterr().err
    assert not (tmp_path / "report.xlsx").exists()


def test_leaves_the_fixture_pdfs_untouched(tmp_path):
    """The CLI is read-only towards its input."""
    before = {p: p.stat().st_mtime_ns for p in sorted(FIXTURES_DIR.glob("*.pdf"))}

    main(["--input", str(FIXTURES_DIR), "--output", str(tmp_path / "report.xlsx")])

    assert {p: p.stat().st_mtime_ns for p in sorted(FIXTURES_DIR.glob("*.pdf"))} == before
