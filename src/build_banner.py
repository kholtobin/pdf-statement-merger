"""Build a before/after banner: a stack of monthly PDFs -> one reconciled Excel report."""

from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]
F_REG, F_BOLD = next(
    (r, b) for r, b in FONT_CANDIDATES if Path(r).exists() and Path(b).exists()
)

# Palette
INK = (31, 41, 51)
MUTED = (110, 120, 130)
EXCEL_GREEN = (33, 115, 70)
FLAG_RED = (176, 42, 42)
GRID = (209, 213, 219)
HEADER_BG = (240, 242, 245)
ROWNUM_BG = (247, 248, 250)
BG = (255, 255, 255)

# Sheet geometry (shared so the arrow can target a specific row)
ROW_H = 34
STRIP_H = 26

# One statement per date/debit convention, back to front.
DISPLAY_PDFS = ["statement_2026_09.pdf", "statement_2026_05.pdf", "statement_2026_01.pdf"]
FAN_DX, FAN_DY = 34, 26  # offset between stacked pages


def font(bold=False, size=22):
    return ImageFont.truetype(F_BOLD if bold else F_REG, size)


def render_pdf(pdf_path: Path, target_h: int) -> Image.Image:
    """Rasterize the first page of a PDF to a PIL image of a given height."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    zoom = (target_h / page.rect.height) * 1.6  # oversample for crispness
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    ratio = target_h / img.height
    img = img.resize((int(img.width * ratio), target_h), Image.LANCZOS)
    bordered = Image.new("RGB", (img.width + 2, img.height + 2), GRID)
    bordered.paste(img, (1, 1))
    return bordered


def render_stack(paths: list[Path], page_h: int) -> Image.Image:
    """Fan several statement pages into one overlapping stack."""
    pages = [render_pdf(p, page_h) for p in paths]
    w = max(p.width for p in pages) + FAN_DX * (len(pages) - 1)
    h = max(p.height for p in pages) + FAN_DY * (len(pages) - 1)
    stack = Image.new("RGB", (w, h), BG)
    for i, p in enumerate(pages):
        stack.paste(p, (FAN_DX * (len(pages) - 1 - i), FAN_DY * i))
    return stack


def render_spreadsheet(df: pd.DataFrame, cols: list[str]) -> Image.Image:
    """Render a DataFrame as an Excel-style grid (column letters + row numbers)."""
    f_reg, f_bold, f_small = font(size=18), font(True, 18), font(size=16)
    pad = 12
    rownum_w = 42
    scratch = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(scratch)

    def cell_text(v):
        if pd.isna(v):
            return ""
        return f"{v:,.2f}" if isinstance(v, float) else str(v)

    def text_w(s, fnt):
        return d.textbbox((0, 0), str(s), font=fnt)[2]

    widths = []
    for c in cols:
        w = text_w(c, f_bold)
        for v in df[c]:
            w = max(w, text_w(cell_text(v), f_reg))
        widths.append(min(w + pad * 2, 360))

    row_h, header_h = ROW_H, STRIP_H
    total_w = rownum_w + sum(widths)
    total_h = header_h + row_h * (len(df) + 1)

    img = Image.new("RGB", (total_w, total_h), BG)
    dr = ImageDraw.Draw(img)

    # Column-letter strip (A, B, C, ...)
    dr.rectangle([0, 0, total_w, header_h], fill=HEADER_BG)
    x = rownum_w
    for i, w in enumerate(widths):
        dr.text((x + w / 2, header_h / 2), chr(ord("A") + i), font=f_small,
                fill=MUTED, anchor="mm")
        x += w

    # Header row
    y = header_h
    dr.rectangle([rownum_w, y, total_w, y + row_h], fill=EXCEL_GREEN)
    x = rownum_w
    for c, w in zip(cols, widths):
        dr.text((x + pad, y + row_h / 2), c, font=f_bold, fill=BG, anchor="lm")
        x += w

    # Data rows
    for r in range(len(df)):
        y = header_h + row_h * (r + 1)
        dr.rectangle([0, y, rownum_w, y + row_h], fill=ROWNUM_BG)
        dr.text((rownum_w / 2, y + row_h / 2), str(r + 1), font=f_small,
                fill=MUTED, anchor="mm")
        x = rownum_w
        for c, w in zip(cols, widths):
            v = df.iloc[r][c]
            s = cell_text(v)
            numeric = isinstance(v, float)
            colour = INK
            if c == "Reconciled":
                colour = EXCEL_GREEN if s == "yes" else FLAG_RED
            elif numeric and v < 0:
                colour = FLAG_RED
            dr.text(
                (x + w - pad if numeric else x + pad, y + row_h / 2),
                s, font=f_reg, fill=colour, anchor="rm" if numeric else "lm",
            )
            x += w

    # Grid lines
    x = rownum_w
    dr.line([rownum_w, header_h, rownum_w, total_h], fill=GRID)
    for w in widths:
        x += w
        dr.line([x, header_h, x, total_h], fill=GRID)
    for r in range(len(df) + 2):
        yy = min(header_h + row_h * r, total_h)
        dr.line([0, yy, total_w, yy], fill=GRID)
    dr.rectangle([0, 0, total_w - 1, total_h - 1], outline=GRID)

    return img


def main() -> None:
    stack_img = render_stack([ROOT / "samples" / p for p in DISPLAY_PDFS], page_h=470)

    report = ROOT / "output" / "report.xlsx"
    df = pd.read_excel(report, sheet_name="Summary").reset_index(drop=True)
    show_cols = ["Month", "Transactions", "Inflows", "Outflows", "Net",
                 "Stated Net", "Reconciled"]
    sheet_img = render_spreadsheet(df[show_cols], show_cols)

    margin, gap, title_h, caption_h = 50, 90, 120, 40
    content_h = max(stack_img.height, sheet_img.height)
    W = margin * 2 + stack_img.width + gap + sheet_img.width
    H = title_h + content_h + caption_h + margin

    banner = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(banner)

    # Title on a single baseline
    tf = font(True, 34)
    ty = margin - 6
    x = margin
    for seg, colour in [("12 Monthly PDFs", INK), ("  →  ", MUTED),
                        ("One Reconciled Excel", EXCEL_GREEN)]:
        dr.text((x, ty), seg, font=tf, fill=colour)
        x += dr.textlength(seg, font=tf)

    top = title_h + (content_h - stack_img.height) // 2
    banner.paste(stack_img, (margin, top))

    sx = margin + stack_img.width + gap
    top_s = title_h + (content_h - sheet_img.height) // 2
    banner.paste(sheet_img, (sx, top_s))

    # Arrow between the panels, aimed at the front statement's summary row
    front_month = DISPLAY_PDFS[-1].removeprefix("statement_").removesuffix(".pdf")
    front_month = front_month.replace("_", "-")
    matches = df.index[df["Month"].astype(str) == front_month].tolist()
    row_idx = matches[0] if matches else 0
    ay = top_s + STRIP_H + ROW_H * (row_idx + 1) + ROW_H // 2
    ax0 = margin + stack_img.width + 18
    ax1 = sx - 18
    dr.line([ax0, ay, ax1 - 14, ay], fill=MUTED, width=4)
    dr.polygon([(ax1, ay), (ax1 - 16, ay - 11), (ax1 - 16, ay + 11)], fill=MUTED)

    # Captions
    cy = title_h + content_h + 8
    cf = font(False, 20)
    dr.text((margin, cy), "Three date formats, two debit conventions", font=cf, fill=MUTED)
    dr.text((sx, cy), "One workbook — every period reconciled to the stated net",
            font=cf, fill=MUTED)

    out = ASSETS / "before-after.png"
    banner.save(out, dpi=(144, 144))
    print(f"wrote {out}  ({banner.width}x{banner.height})")


if __name__ == "__main__":
    main()
