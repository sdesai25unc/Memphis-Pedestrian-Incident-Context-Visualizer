r"""
docs/build_handoff_pdf.py
=========================

Regenerates HANDOFF.pdf from HANDOFF.md — a print-quality handoff document for
non-technical recipients: unnumbered title page, table of contents with REAL page
numbers (two-pass render), "Page X of Y" footers, Geist typography (same fontsource
CDN the site uses; falls back to system sans offline).

Formatting notes (content is never altered — only presentation):
  - The 4-column data-sources table (Source/Origin/Refresh/Caveats) cannot fit a
    portrait page (in a naive render the Caveats column clips off the page edge),
    so THAT table alone is reflowed into stacked labeled blocks. Every word kept.
  - h2 sections start on a new page; the TOC lists h2 + h3.

Dependencies (in the project venv): markdown, pypdf, playwright (+ installed Chrome).

Run it after editing HANDOFF.md:
    .\.venv\Scripts\python.exe docs\build_handoff_pdf.py
"""

import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import markdown
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parent.parent
MD = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
OUT = ROOT / "HANDOFF.pdf"
TMP = Path(tempfile.mkdtemp(prefix="handoff_pdf_"))

TITLE_DATE = date.today().strftime("%B %d, %Y").replace(" 0", " ")

# ---------- collect headings (h2/h3) for the TOC, in order ----------
heads = []
for m in re.finditer(r"^(##|###) (.+)$", MD, re.M):
    heads.append([len(m.group(1)), re.sub(r"\*|`", "", m.group(2)).strip(), f"h{len(heads)}"])

body_html = markdown.markdown(MD, extensions=["tables", "sane_lists", "smarty"])
_i = -1
def _tag(m):
    global _i
    _i += 1
    return f'<{m.group(1)} id="h{_i}">'
body_html = re.sub(r"<(h[23])>", _tag, body_html)


def _stack_wide_table(html):
    """Reflow the 4-column data-sources table into stacked blocks (print can't fit it)."""
    for m in re.finditer(r"<table>.*?</table>", html, re.S):
        tbl = m.group(0)
        headers = re.findall(r"<th>(.*?)</th>", tbl, re.S)
        if not (len(headers) == 4 and "Refresh" in " ".join(headers)):
            continue
        blocks = ['<div class="srclist">']
        for row in re.findall(r"<tr>(.*?)</tr>", tbl, re.S):
            cells = re.findall(r"<td>(.*?)</td>", row, re.S)
            if len(cells) != 4:
                continue
            name, origin, refresh, caveats = cells
            blocks.append(
                f'<div class="srcblock"><div class="srcname">{name}</div>'
                f'<p><span class="srclabel">Origin.</span> {origin}</p>'
                f'<p><span class="srclabel">Refresh.</span> {refresh}</p>'
                f'<p><span class="srclabel">Caveats.</span> {caveats}</p></div>')
        blocks.append("</div>")
        return html.replace(tbl, "".join(blocks))
    return html


body_html = _stack_wide_table(body_html)

CSS = """
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/400.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/500.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/600.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/700.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-mono@5.2.5/400.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-mono@5.2.5/500.css');
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: 'Geist Sans', Inter, 'Segoe UI', Arial, sans-serif; color: #18181b;
       font-size: 10.3pt; line-height: 1.62; }
h1 { font-size: 21pt; letter-spacing: -.02em; margin: 0 0 4pt; line-height: 1.15; }
h2 { font-size: 15pt; letter-spacing: -.015em; margin: 0 0 10pt; padding-bottom: 6pt;
     border-bottom: 1.2pt solid #e4e4e7; break-after: avoid; }
h2:not(:first-of-type) { break-before: page; }
h3 { font-size: 11.5pt; margin: 16pt 0 6pt; break-after: avoid; }
p { margin: 7pt 0; }
em { color: #3f3f46; }
a { color: #4338ca; text-decoration: none; }
ul, ol { margin: 6pt 0; padding-left: 20pt; }
li { margin: 3pt 0; }
hr { border: none; border-top: 1pt solid #e4e4e7; margin: 14pt 0; }
code { font-family: 'Geist Mono', Consolas, monospace; font-size: 8.8pt; background: #f4f4f5;
       border: .6pt solid #e4e4e7; border-radius: 3pt; padding: .5pt 3pt;
       overflow-wrap: anywhere; }
th { white-space: nowrap; }
td { overflow-wrap: break-word; }
blockquote { margin: 10pt 0; padding: 8pt 13pt; background: #fafafa;
             border-left: 2.5pt solid #a1a1aa; color: #3f3f46; }
blockquote p { margin: 4pt 0; }
table { border-collapse: collapse; width: 100%; margin: 9pt 0; font-size: 8.9pt; line-height: 1.5; }
th { background: #f4f4f5; text-align: left; font-weight: 600; font-size: 8.3pt;
     text-transform: uppercase; letter-spacing: .04em; color: #3f3f46; }
th, td { border: .6pt solid #d4d4d8; padding: 5pt 7pt; vertical-align: top; }
tr { break-inside: avoid; }
strong { color: #111114; }
.srcblock { margin: 10pt 0 12pt; padding-left: 10pt; border-left: 2pt solid #e4e4e7; }
.srcname { font-weight: 700; font-size: 10.8pt; margin-bottom: 2pt; break-after: avoid; }
.srclabel { font-weight: 600; color: #3f3f46; font-size: 8.6pt; text-transform: uppercase;
            letter-spacing: .05em; margin-right: 2pt; }
.srcblock p { margin: 4pt 0; }
#toc h2 { border-bottom: 1.2pt solid #e4e4e7; }
#toc .row { display: flex; align-items: baseline; margin: 4.5pt 0; font-size: 10.3pt; }
#toc .row.l3 { padding-left: 16pt; font-size: 9.6pt; color: #3f3f46; }
#toc .t { flex: none; max-width: 82%; }
#toc .dots { flex: 1; border-bottom: 1pt dotted #a1a1aa; margin: 0 6pt; transform: translateY(-2.5pt); }
#toc .p { flex: none; font-family: 'Geist Mono', Consolas, monospace; font-size: 9pt; color: #3f3f46; }
#toc { break-after: page; }
"""

TITLE_CSS = """
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/400.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/600.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/700.css');
@import url('https://cdn.jsdelivr.net/npm/@fontsource/geist-mono@5.2.5/400.css');
html, body { margin: 0; padding: 0; height: 100%; }
body { font-family: 'Geist Sans', Inter, 'Segoe UI', Arial, sans-serif; color: #18181b;
       display: flex; flex-direction: column; }
.mid { flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 0 .9in; }
.mark { width: 44px; height: 44px; border-radius: 10px; background: #18181b; position: relative; margin-bottom: 26px; }
.mark::before { content: ""; position: absolute; left: 9px; bottom: 9px; width: 13px; height: 13px;
                border-radius: 50%; background: #1b9e8f; }
.mark::after { content: ""; position: absolute; right: 9px; top: 9px; width: 13px; height: 13px;
               border-radius: 50%; background: #d6453d; }
.eyebrow { font-family: 'Geist Mono', Consolas, monospace; font-size: 9.5pt; letter-spacing: .12em;
           text-transform: uppercase; color: #71717a; margin-bottom: 14pt; }
h1 { font-size: 34pt; letter-spacing: -.03em; margin: 0; line-height: 1.08; }
.sub { font-size: 15pt; color: #3f3f46; margin-top: 8pt; }
.rule { width: 64px; border-top: 3px solid #18181b; margin: 26pt 0; }
.meta { font-size: 11.5pt; color: #3f3f46; line-height: 1.9; }
.meta b { color: #18181b; }
.foot { padding: 0 .9in .8in; font-size: 9pt; color: #a1a1aa; line-height: 1.6; }
"""

TITLE_HTML = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{TITLE_CSS}</style></head>
<body>
  <div class="mid">
    <div class="mark"></div>
    <div class="eyebrow">Innovate Memphis</div>
    <h1>StreetStat</h1>
    <div class="sub">Project Handoff Documentation</div>
    <div class="rule"></div>
    <div class="meta">
      <b>Prepared by</b> Samarth Desai<br>
      <b>Date</b> {TITLE_DATE}<br>
      <b>Live site</b> streetstat.org
    </div>
  </div>
  <div class="foot">Pedestrian crash &amp; infrastructure context for Memphis — data, methodology,
    operations, and known open items. This document is the complete, unabridged handoff: every
    caveat and open item is included by design.</div>
</body></html>"""


def toc_html(page_nums):
    rows = []
    for level, text, anchor in heads:
        pn = page_nums.get(anchor, "&bull;")
        rows.append(f'<div class="row l{level}"><span class="t">{text}</span>'
                    f'<span class="dots"></span><span class="p">{pn}</span></div>')
    return '<div id="toc"><h2 style="break-before:auto">Contents</h2>' + "".join(rows) + "</div>"


def body_doc(page_nums):
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>'
            + toc_html(page_nums) + body_html + "</body></html>")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from playwright.sync_api import sync_playwright

    def render(ctx, html, pdf_path, footer):
        pg = ctx.new_page()
        pg.set_content(html, wait_until="load")
        pg.wait_for_function("document.fonts && document.fonts.status === 'loaded'", timeout=30000)
        pg.wait_for_timeout(300)
        opts = dict(path=str(pdf_path), format="Letter", print_background=True,
                    margin={"top": "0.85in", "bottom": "0.85in", "left": "0.9in", "right": "0.9in"})
        if footer:
            opts.update(display_header_footer=True,
                header_template='<div style="font-size:7.5pt;color:#a1a1aa;width:100%;padding:0 0.9in;'
                                'font-family:Arial,sans-serif;">StreetStat &mdash; Project Handoff Documentation</div>',
                footer_template='<div style="font-size:7.5pt;color:#a1a1aa;width:100%;padding:0 0.9in;'
                                'font-family:Arial,sans-serif;display:flex;justify-content:space-between;">'
                                '<span>Innovate Memphis</span>'
                                '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
        else:
            opts.update(margin={"top": "0in", "bottom": "0in", "left": "0in", "right": "0in"})
        pg.pdf(**opts)
        pg.close()

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context()

        # pass 1: placeholder TOC -> locate each heading's page
        body_p1 = TMP / "body_p1.pdf"
        render(ctx, body_doc({}), body_p1, footer=True)
        reader = PdfReader(str(body_p1))

        def squish(s):
            return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", s)).strip().lower()

        pages_sq = [squish(pg.extract_text() or "") for pg in reader.pages]
        page_nums = {}
        for level, text, anchor in heads:
            hits = [i + 1 for i, t in enumerate(pages_sq) if squish(text) in t]
            if hits:                       # heading also appears in the TOC -> take the LAST hit
                page_nums[anchor] = hits[-1]
        missing = [h[1] for h in heads if h[2] not in page_nums]
        print(f"pass 1: {len(reader.pages)} body pages; TOC resolved {len(page_nums)}/{len(heads)}"
              + (f"; MISSING: {missing}" if missing else ""))

        # pass 2 + title page
        body_p2 = TMP / "body.pdf"
        render(ctx, body_doc(page_nums), body_p2, footer=True)
        title_p = TMP / "title.pdf"
        render(ctx, TITLE_HTML, title_p, footer=False)
        b.close()

    w = PdfWriter()
    for src in (title_p, body_p2):
        for pg in PdfReader(str(src)).pages:
            w.add_page(pg)
    with open(OUT, "wb") as f:
        w.write(f)
    print(f"wrote {OUT}  ({len(PdfReader(str(OUT)).pages)} pages, {OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
