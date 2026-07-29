"""Search staff resumes by any word in them.

    py -m src.resumes index "<drive>:\\path\\to\\Master Resumes"
    py -m src.resumes search signals

Folders starting with _ are skipped (old files, people who left).
Name comes from the filename: "Joe Clark_NBIS Resume.docx" -> Joe Clark.
"""

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "resumes_index.json"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_text(docx_path: Path) -> str:
    """Read the raw XML because the resume template puts text in
    text boxes, which python-docx can't see."""
    parts = []
    with zipfile.ZipFile(docx_path) as z:
        names = [
            n for n in z.namelist()
            if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)
        ]
        for name in sorted(names, key=lambda n: n != "word/document.xml"):
            root = ElementTree.fromstring(z.read(name))
            for para in root.iter(f"{W}p"):
                text = "".join(node.text or "" for node in para.iter(f"{W}t"))
                if text.strip():
                    parts.append(text.strip())
    return "\n".join(parts)


# Trailing filler words that belong to the variant, not the person's name
# ("Drew Jacob Update Resume 2025" -> Drew Jacob).
NAME_STOP = {"resume", "resumes", "rsume", "new", "newresume", "updated",
             "update", "master", "site", "vs"}


def person_and_variant(stem: str) -> tuple[str, str]:
    name, _, variant = stem.partition("_")
    if not variant.strip() and "-" in name:  # "ALAN BALL- New Resume"
        name, _, variant = name.partition("-")
    tokens = name.split()
    stripped = []
    while tokens and (
        tokens[-1].lower().strip("()") in NAME_STOP
        or tokens[-1].strip("()").replace(".", "").isdigit()
    ):
        stripped.insert(0, tokens.pop())
    name = " ".join(tokens).strip() or stem
    if name.isupper():  # "MITCH LANKFORD" -> "Mitch Lankford"
        name = name.title()
    variant = variant.strip() or " ".join(stripped) or "Resume"
    return name, variant


def build_index(resumes_dir: Path) -> list[dict]:
    entries = []
    skipped_doc = []
    for path in sorted(resumes_dir.rglob("*")):
        if path.name.startswith("~$"):  # Word lock files
            continue
        rel_parts = path.relative_to(resumes_dir).parts
        if any(part.startswith("_") for part in rel_parts[:-1]):
            continue  # _Archives, _No Longer Works at VS, _PDF, ...
        if re.search(r"template|resume form", path.stem, re.IGNORECASE):
            continue
        if path.suffix.lower() == ".doc":
            skipped_doc.append(path)  # old-format .doc needs Word to convert
            continue
        if path.suffix.lower() != ".docx":
            continue
        try:
            text = extract_text(path)
        except Exception as exc:  # unreadable/corrupt file — index the rest
            print(f"  ! could not read {path.name}: {exc}")
            continue
        person, variant = person_and_variant(path.stem)
        entries.append(
            {
                "file": str(path.resolve()),
                "person": person,
                "variant": variant,
                "discipline": rel_parts[0] if len(rel_parts) > 1 else "",
                "text": text,
                "modified": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
            }
        )
        print(f"  {person} — {variant} ({entries[-1]['discipline']})")
    if skipped_doc:
        print(f"\nSkipped {len(skipped_doc)} old-format .doc file(s) — open in Word and save as .docx:")
        for path in skipped_doc:
            print(f"  {path}")
    return entries


def snippet(text: str, term: str, width: int = 70) -> str:
    """A little context around the first hit, so results show *why* they match."""
    pos = text.lower().find(term.lower())
    if pos < 0:
        return ""
    start = max(0, pos - width)
    end = min(len(text), pos + len(term) + width)
    piece = " ".join(text[start:end].split())
    return f"...{piece}..."


def search_resumes(terms: list[str]) -> list[dict]:
    if not INDEX_PATH.exists():
        sys.exit('No resume index yet — run:  py -m src.resumes index "<resumes folder>"')
    entries = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    terms = [t.strip(".,;:") for t in terms if t.strip(".,;:")]
    results = []
    for entry in entries:
        person = entry["person"].lower()
        # "signal" should also hit Desai's "Signal Resume" by its filename.
        labels = f"{entry['variant']} {entry['discipline']}".lower()
        text = entry["text"].lower()
        score = 0
        best_snippet = ""
        for term in terms:
            t = term.lower()
            if t in person:
                score += 10  # name hits outrank text mentions
            elif t in labels:
                score += 5 + len(re.findall(re.escape(t), text))
                best_snippet = best_snippet or snippet(entry["text"], t)
            elif t in text:
                score += len(re.findall(re.escape(t), text))
                best_snippet = best_snippet or snippet(entry["text"], t)
            else:
                score = 0
                break  # every term must match somewhere
        if score:
            results.append(
                {
                    "score": score,
                    "snippet": best_snippet,
                    **{k: entry[k] for k in ("file", "person", "variant", "discipline", "modified")},
                }
            )
    results.sort(key=lambda r: -r["score"])
    return results


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Index and search staff resumes.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Scan a folder of .docx resumes")
    p_index.add_argument("folder", help="Path to the master resumes folder")

    p_search = sub.add_parser("search", help="Full-text search the resumes")
    p_search.add_argument("terms", nargs="+", help="Keywords; all must match")

    args = parser.parse_args()

    if args.command == "index":
        folder = Path(args.folder)
        if not folder.is_dir():
            sys.exit(f"Not a folder: {folder}")
        print(f"Indexing {folder} ...")
        entries = build_index(folder)
        INDEX_PATH.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nIndexed {len(entries)} resume(s) -> {INDEX_PATH}")

    elif args.command == "search":
        results = search_resumes(args.terms)
        if not results:
            print("No matches.")
            return 1
        print(f"{len(results)} match(es):\n")
        for r in results:
            print(f"  {r['person']} — {r['variant']}  [{r['discipline']}]")
            if r["snippet"]:
                print(f"    {r['snippet']}")
            print(f"    file: {r['file']}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
