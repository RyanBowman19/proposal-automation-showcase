"""Compare our LOI against a competitor's, section by section.

    py -m src.compare "2605 Item 5"                  # vs the winner
    py -m src.compare "2604 Item 4" --against 2       # vs 2nd place
    py -m src.compare "2605 Item 5" --against all     # vs every ranked competitor
    py -m src.compare "2605 Item 5" --vs "C:\\...\\draft.pdf"   # a draft that
        hasn't been filed/scored yet, benchmarked against this pursuit's
        competitors as the closest available comparison

Uses the files in reference/proposal-analysis (the marketing team's folder layout).
Questions live in questions.yaml - same ones every run on purpose.
Scoring criteria go in; actual scores stay out (avoids biasing the AI's read).
Everything for a pursuit lands together in output/<pursuit slug>/, as both
a .docx (open this one) and a .md (source).

For running the mistake checker and this together in one pass, see
src/review.py instead.

Needs an Anthropic API key the first time:
    setx ANTHROPIC_API_KEY "sk-ant-..."   (then open a new window)
"""

import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

import anthropic
import yaml
from docx import Document
from docx.shared import Pt
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "reference" / "proposal-analysis"
OUT = ROOT / "output"
MODEL = "claude-opus-4-8"
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

INSTRUCTIONS = """You are helping VS Engineering figure out why their INDOT \
letters of interest score mid-pack. You'll get the scoring criteria, VS's LOI, \
and a competitor's LOI, then be asked about one section at a time.

Judge like an INDOT selection committee member scoring against the criteria. \
Be blunt and specific: quote short phrases from both documents as evidence, \
say which firm is stronger on that section and why, and end with what VS \
should do differently. Don't pad or soften."""


def pdf_text(path: Path) -> str:
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def parse_pursuit(pursuit: str) -> tuple[str, str]:
    """'2605 Item 5' -> ('2605', '5')"""
    m = re.fullmatch(r"(\d{4})\s*item\s*(\d+)", pursuit.strip(), re.IGNORECASE)
    if not m:
        sys.exit('Pursuit should look like: "2605 Item 5"')
    return m.group(1), str(int(m.group(2)))


def default_vs_path(rfp: str, item: str) -> Path:
    """Where our own filed LOI lives for a finished, scored pursuit."""
    return DATA / "VS Proposals" / f"RFP {rfp}-VS-Item {int(item):02d}-LOI.pdf"


def available_ranks(rfp: str, item: str) -> list[int]:
    """Which competitor ranks exist for this pursuit, e.g. [1, 2, 3]."""
    comp_dir = DATA / "Competitors" / f"{rfp} Item {item}"
    ranks = {int(m.group(1)) for p in comp_dir.glob("*_*.pdf")
             if (m := re.match(r"(\d+)_", p.name))}
    return sorted(ranks)


def out_dir_for(pursuit: str) -> Path:
    """Where a pursuit's check/comparison reports live, e.g.
    output/2605-item-5/."""
    slug = re.sub(r"\W+", "-", pursuit.lower())
    return OUT / slug


def find_files(pursuit: str, against: int, vs_path: str | Path | None = None) -> dict:
    """Locate the VS (or draft) LOI, competitor LOI, and criteria for e.g.
    '2605 Item 5'. vs_path overrides which LOI gets scored - use it for a
    draft that hasn't been filed under VS Proposals yet. Either way, the
    competitor and criteria always come from `pursuit`'s own folder, since
    that's the closest available benchmark."""
    rfp, item = parse_pursuit(pursuit)

    if vs_path:
        vs = Path(vs_path)
        if not vs.exists():
            sys.exit(f"Can't find that LOI: {vs}")
    else:
        vs = default_vs_path(rfp, item)
        if not vs.exists():
            sys.exit(f"Can't find our LOI: {vs}")

    comp_dir = DATA / "Competitors" / f"{rfp} Item {item}"
    comps = sorted(comp_dir.glob(f"{against}_*.pdf"))
    if not comps:
        sys.exit(f"No competitor ranked {against} in {comp_dir}")
    competitor = comps[0]

    # Criteria/RFP doc for this item, e.g. "Advertised 2604 ITEM 4 Criteria.pdf"
    # or "Advertised 2605_Item 5.pdf" - naming varies, so match loosely.
    rfp_dir = DATA / rfp
    candidates = [
        p for p in rfp_dir.glob("*.pdf")
        if re.search(rf"item\s*_?\s*0?{item}\b", p.stem, re.IGNORECASE)
        and "scoresheet" not in p.stem.replace(" ", "").lower()
    ]
    candidates.sort(key=lambda p: "criteria" not in p.stem.lower())
    if not candidates:
        sys.exit(f"No criteria/RFP doc for item {item} in {rfp_dir}")

    return {
        "vs": vs,
        "competitor": competitor,
        "criteria": candidates[0],
        "who": competitor_name(competitor, rfp_dir),
    }


def competitor_name(path: Path, rfp_dir: Path) -> str:
    """Get the firm name from the score sheet filenames, e.g.
    '2605 Item 5_FinalScoreSheet_PARSONS.pdf' -> PARSONS."""
    key = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    for sheet in rfp_dir.glob("*FinalScoreSheet_*.pdf"):
        firm = sheet.stem.rsplit("_", 1)[-1]
        norm = re.sub(r"[^a-z0-9]", "", firm.lower())
        if norm != "vs" and norm in key:
            return firm.title() if firm.isupper() else firm
    return re.sub(r"^\d+_", "", path.stem)  # fall back to the filename


# --- Turns a markdown report into a Word doc or a web page. Both readers
# share one parser so the two outputs always match. Only handles what
# Claude's answers actually use: #/## headings, **bold**, and lists.

def _parse_blocks(md_text: str):
    """Split a report into (kind, content) pieces: headings, paragraphs,
    numbered lists, bulleted lists. Blocks are separated by a blank line."""
    for block in re.split(r"\n\s*\n", md_text.strip()):
        block = block.strip()
        if not block:
            continue
        if block.startswith("# "):
            yield "h0", block[2:].strip()
            continue
        if block.startswith("## "):
            yield "h1", block[3:].strip()
            continue

        first = block.lstrip().splitlines()[0].lstrip()
        if re.match(r"^\d+\.\s", first):
            marker, kind = r"^\d+\.\s*", "list-number"
        elif first[:2] in ("- ", "* "):
            marker, kind = r"^[-*]\s*", "list-bullet"
        else:
            yield "p", re.sub(r"\s+", " ", block).strip()
            continue

        # Claude's answers wrap long lines, so one list item can span
        # several lines. Only start a new item where a line actually
        # begins with "1. " / "- " / "* " - everything else is a
        # continuation of the item above and gets joined back in.
        items = [re.sub(marker, "", re.sub(r"\s+", " ", it).strip())
                 for it in re.split(r"\n(?=\d+\.\s|-\s|\*\s)", block)]
        yield kind, items


def _add_rich_paragraph(doc, text, style=None):
    """One Word paragraph. Turns **bold** into an actual bold run."""
    p = doc.add_paragraph(style=style)
    pos = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > pos:
            p.add_run(text[pos:m.start()])  # plain text before the bold bit
        p.add_run(m.group(1)).bold = True
        pos = m.end()
    if pos < len(text):
        p.add_run(text[pos:])  # whatever's left after the last bold bit
    return p


def markdown_to_docx(md_text: str, out_path: Path) -> Path:
    doc = Document()
    for kind, content in _parse_blocks(md_text):
        if kind == "h0":
            doc.add_heading(content, level=0)
        elif kind == "h1":
            doc.add_heading(content, level=1)
        elif kind == "p":
            _add_rich_paragraph(doc, content)
        elif kind == "list-number":
            for item in content:
                _add_rich_paragraph(doc, item, style="List Number")
        elif kind == "list-bullet":
            for item in content:
                _add_rich_paragraph(doc, item, style="List Bullet")

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def _bold_to_html(text: str) -> str:
    """Escape the text for HTML, then turn **bold** into <strong>."""
    parts = []
    pos = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > pos:
            parts.append(html.escape(text[pos:m.start()]))
        parts.append(f"<strong>{html.escape(m.group(1))}</strong>")
        pos = m.end()
    parts.append(html.escape(text[pos:]))
    return "".join(parts)


def markdown_to_html(md_text: str) -> str:
    """Same report as markdown_to_docx, as an HTML snippet - so it can be
    read right on the search page instead of opening Word."""
    out = []
    for kind, content in _parse_blocks(md_text):
        if kind == "h0":
            out.append(f"<h2>{_bold_to_html(content)}</h2>")
        elif kind == "h1":
            out.append(f"<h3>{_bold_to_html(content)}</h3>")
        elif kind == "p":
            out.append(f"<p>{_bold_to_html(content)}</p>")
        elif kind == "list-number":
            items = "".join(f"<li>{_bold_to_html(i)}</li>" for i in content)
            out.append(f"<ol>{items}</ol>")
        elif kind == "list-bullet":
            items = "".join(f"<li>{_bold_to_html(i)}</li>" for i in content)
            out.append(f"<ul>{items}</ul>")
    return "\n".join(out)


def run(pursuit: str, against: int, vs_path: str | Path | None = None) -> Path:
    files = find_files(pursuit, against, vs_path)
    who = files.pop("who")
    # A draft gets its own filename as the label, since it isn't really
    # "VS's <pursuit> LOI" - it's being benchmarked against that pursuit's
    # winner as the closest available comparison.
    us = Path(vs_path).stem if vs_path else "VS Engineering"
    print(f"Comparing {us} vs {who} (benchmark: {pursuit})")
    for label, path in files.items():
        print(f"  {label}: {path.name}")

    docs = "\n\n".join(
        f"=== {title} ===\n{pdf_text(path)}"
        for title, path in [
            ("SCORING CRITERIA / RFP", files["criteria"]),
            ("VS ENGINEERING LOI", files["vs"]),
            (f"COMPETITOR LOI ({who})", files["competitor"]),
        ]
    )

    questions = yaml.safe_load((ROOT / "questions.yaml").read_text(encoding="utf-8"))
    client = anthropic.Anthropic()

    report = [
        f"# LOI comparison: {us} vs {who} (benchmark: {pursuit})",
        f"\nGenerated {date.today()} by src/compare.py. "
        f"Same questions every run (questions.yaml).\n",
    ]
    for q in questions:
        print(f"  asking about: {q['section']} ...")
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=[
                {"type": "text", "text": INSTRUCTIONS},
                # Cached so the 6 questions don't re-pay for the documents.
                {"type": "text", "text": docs, "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": q["question"]}],
        )
        answer = "".join(b.text for b in response.content if b.type == "text")
        report.append(f"\n## {q['section']}\n\n{answer}\n")

    out_dir = out_dir_for(pursuit)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"vs_{re.sub(r'\W+', '-', who)}"
    if vs_path:
        name = f"draft-{re.sub(r'\W+', '-', Path(vs_path).stem)}_{name}"
    stem = out_dir / name
    md_text = "\n".join(report)
    stem.with_suffix(".md").write_text(md_text, encoding="utf-8")
    markdown_to_docx(md_text, stem.with_suffix(".docx"))
    return stem.with_suffix(".docx")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Compare our LOI against a competitor's.")
    parser.add_argument("pursuit", help='e.g. "2605 Item 5" - which pursuit\'s '
                        "competitor data to benchmark against")
    parser.add_argument("--against", default="1",
                        help='competitor rank: 1 = winner (default), 2, 3, or "all"')
    parser.add_argument("--vs", help="Path to a specific LOI to score, instead of "
                        "the one filed under reference/proposal-analysis/VS Proposals. "
                        "Use this for a draft that hasn't been submitted/scored yet.")
    args = parser.parse_args()

    rfp, item = parse_pursuit(args.pursuit)
    if args.against.lower() == "all":
        ranks = available_ranks(rfp, item)
        if not ranks:
            sys.exit(f"No competitors found for {args.pursuit}")
    else:
        ranks = [int(args.against)]

    try:
        out_paths = [run(args.pursuit, rank, args.vs) for rank in ranks]
    except anthropic.AuthenticationError:
        sys.exit("API key is missing or wrong. Set it with:\n"
                 '  setx ANTHROPIC_API_KEY "sk-ant-..."\n'
                 "then open a new window. Keys: console.anthropic.com")
    except TypeError as exc:
        if "auth" in str(exc).lower():
            sys.exit("No API key set. Run:\n"
                     '  setx ANTHROPIC_API_KEY "sk-ant-..."\n'
                     "then open a new window. Keys: console.anthropic.com")
        raise
    print(f"\nDone. {len(out_paths)} report(s):")
    for p in out_paths:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
