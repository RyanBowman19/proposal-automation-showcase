"""Check a finished LOI PDF for mistakes before it goes out.

    py -m src.check "path\\to\\LOI.pdf"
    py -m src.check "LOI.pdf" --rfp 2605 --item 5 --client INDOT --max-pages 12

Or drag the PDF onto Check LOI.bat.

Catches: wrong RFP/item numbers (a real one shipped: "RFP 2506" in every
footer of a 2605 LOI), wrong client names left over from reused templates,
doubled words, page limit, and likely typos. Word lists live in checks.yaml -
add names/jargon there when something gets flagged that's fine.

ERRORS are almost certainly real. CHECK THESE are worth a look.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import fitz
import yaml
from spellchecker import SpellChecker

ROOT = Path(__file__).resolve().parent.parent
CHECKS_PATH = ROOT / "checks.yaml"


def load_pages(pdf_path: Path) -> list[str]:
    doc = fitz.open(pdf_path)
    return [page.get_text() for page in doc]


def expected_from_filename(name: str) -> tuple[str | None, str | None]:
    """'RFP 2605-VS-Item 05-LOI.pdf' -> ('2605', '5')"""
    rfp = re.search(r"\b(2\d{3})\b", name)
    item = re.search(r"item\s*_?-?\s*0?(\d{1,2})", name, re.IGNORECASE)
    return (rfp.group(1) if rfp else None, item.group(1) if item else None)


def check_numbers(pages, kind, pattern, expected, findings):
    """Flag every page where an RFP/item number doesn't match the expected one."""
    seen = Counter()
    hits = []  # (page, value)
    for num, text in enumerate(pages, 1):
        for m in re.finditer(pattern, text, re.IGNORECASE):
            seen[m.group(1).lstrip("0") or "0"] += 1
            hits.append((num, m.group(1).lstrip("0") or "0"))
    if not seen:
        return
    if expected is None:
        expected = seen.most_common(1)[0][0]
        if len(seen) > 1:
            findings["errors"].append(
                f"{kind} numbers disagree: {dict(seen)}. "
                f"Guessing {expected} is right - pass --{kind.split()[0].lower()} to be sure.")
    wrong_pages = sorted({p for p, v in hits if v != expected.lstrip('0')})
    if wrong_pages:
        wrong_vals = {v for _, v in hits if v != expected.lstrip("0")}
        findings["errors"].append(
            f"Wrong {kind} number {', '.join(sorted(wrong_vals))} "
            f"(should be {expected}) on page(s): {', '.join(map(str, wrong_pages))}")


def check_clients(pages, client, clients, findings):
    if not client:
        return
    for name in clients:
        if name.lower() == client.lower():
            continue
        bad = [n for n, text in enumerate(pages, 1)
               if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE)]
        if bad:
            findings["errors"].append(
                f'Found "{name}" but this LOI is for {client} - '
                f"page(s): {', '.join(map(str, bad))}")


def check_doubles(pages, findings):
    for num, text in enumerate(pages, 1):
        # Same line only - words stacked in table columns aren't doubles.
        for m in re.finditer(r"\b([A-Za-z]{2,})[ \t]+\1\b", text):
            word = m.group(1)
            if word.lower() in ("that",):  # "that that" can be legit
                continue
            findings["check"].append(f'Doubled word "{word} {word}" on page {num}')


def staff_names() -> set[str]:
    """Names from the resume and profile indexes, so VS staff never get
    flagged as typos. Works fine if the indexes aren't there."""
    import json
    names = set()
    for index in (ROOT / "resumes_index.json", ROOT / "profiles_index.json"):
        if index.exists():
            for entry in json.loads(index.read_text(encoding="utf-8")):
                for field in ("person", "people"):
                    val = entry.get(field, [])
                    for name in ([val] if isinstance(val, str) else val):
                        names.update(w.lower() for w in re.findall(r"[A-Za-z]{2,}", name))
                        # "DylanBarthel" -> dylan, barthel
                        names.update(w.lower() for w in re.findall(r"[A-Z][a-z]+", name))
    return names


def check_spelling(pages, ok_words, findings):
    """Flag words the dictionary doesn't know. Names get flagged too -
    add them to checks.yaml once and they stay quiet."""
    spell = SpellChecker()
    ok = {w.lower() for w in ok_words} | staff_names()
    spell.word_frequency.load_words(ok)
    counts = Counter()
    first_page = {}
    for num, text in enumerate(pages, 1):
        # Emails and web addresses aren't words.
        text = re.sub(r"\S+@\S+|www\.\S+|\S+\.(com|org|net|gov)\b", " ", text)
        for word in re.findall(r"[A-Za-z]{4,}", text):
            w = word.lower()
            counts[w] += 1
            first_page.setdefault(w, num)
    unknown = spell.unknown(counts.keys())
    for w in sorted(unknown, key=lambda w: first_page[w]):
        if counts[w] >= 5:
            continue  # shows up a lot - probably a name or product, not a typo
        if w.rstrip("s") in ok or (w.endswith("s") and not spell.unknown([w[:-1]])):
            continue  # plural of a fine word
        fix = spell.correction(w)
        if fix and fix != w:
            findings["check"].append(
                f'Possible typo "{w}" on page {first_page[w]}'
                + (f" (x{counts[w]})" if counts[w] > 1 else "")
                + f' - did you mean "{fix}"?')


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Check a finished LOI PDF for mistakes.")
    parser.add_argument("pdf", help="Path to the LOI PDF")
    parser.add_argument("--rfp", help="Correct RFP number, e.g. 2605")
    parser.add_argument("--item", help="Correct item number, e.g. 5")
    parser.add_argument("--client", help="Who this LOI is for, e.g. INDOT")
    parser.add_argument("--max-pages", type=int, help="Page limit, e.g. 12")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"Not found: {pdf_path}")
    pages = load_pages(pdf_path)
    rules = yaml.safe_load(CHECKS_PATH.read_text(encoding="utf-8"))

    guessed_rfp, guessed_item = expected_from_filename(pdf_path.name)
    rfp = args.rfp or guessed_rfp
    item = args.item or guessed_item

    print(f"Checking {pdf_path.name} ({len(pages)} pages)")
    print(f"Expecting: RFP {rfp or '?'}, Item {item or '?'}, "
          f"client {args.client or '(not given - skipping client check)'}\n")

    findings = {"errors": [], "check": []}

    if args.max_pages and len(pages) > args.max_pages:
        findings["errors"].append(
            f"{len(pages)} pages but the limit is {args.max_pages}")
    check_numbers(pages, "RFP", r"(?:RFP|INDOT)\s*#?\s*(2\d{3})\b", rfp, findings)
    check_numbers(pages, "Item", r"Item\s*#?\s*-?\s*0?(\d{1,2})\b", item, findings)
    check_clients(pages, args.client, rules.get("clients", []), findings)
    check_doubles(pages, findings)
    check_spelling(pages, rules.get("ok_words", []), findings)

    if findings["errors"]:
        print(f"ERRORS ({len(findings['errors'])}) - fix before sending:")
        for f in findings["errors"]:
            print(f"  ! {f}")
    else:
        print("No errors found.")
    if findings["check"]:
        print(f"\nCHECK THESE ({len(findings['check'])}):")
        for f in findings["check"]:
            print(f"  ? {f}")
    print("\nFalse alarm? Add the word to checks.yaml and it stays quiet.")
    return 1 if findings["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
