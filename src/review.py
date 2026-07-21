"""Runs the mistake checker and the comparison tool together, one pursuit
at a time, so you don't have to run src.check and src.compare separately.

    py -m src.review "2605 Item 5"
    py -m src.review "2605 Item 5" --against 1
    py -m src.review "2604 Item 11" --vs "C:\\path\\to\\draft-loi.pdf"

Everything lands together in output/<pursuit slug>/.
Needs an Anthropic API key the first time (see src/compare.py).
"""

import argparse
import sys
from pathlib import Path

import yaml

from . import check, compare


def review(pursuit: str, against: str, vs_path: str | None, client: str,
           rfp_override: str | None, item_override: str | None,
           max_pages: int | None) -> Path:
    # bench_rfp/bench_item say whose competitor data to compare against.
    # check_rfp/check_item say what number the mistake checker should
    # actually expect in the footer - only the same thing when you're not
    # using --vs. A draft for a brand-new RFP shouldn't get flagged for not
    # saying the old pursuit's number.
    bench_rfp, bench_item = compare.parse_pursuit(pursuit)

    if vs_path:
        vs = Path(vs_path)
        if not vs.exists():
            sys.exit(f"Can't find that LOI: {vs}")
        guessed_rfp, guessed_item = check.expected_from_filename(vs.name)
        check_rfp = rfp_override or guessed_rfp
        check_item = item_override or guessed_item
    else:
        vs = compare.default_vs_path(bench_rfp, bench_item)
        if not vs.exists():
            sys.exit(f"Can't find our LOI: {vs}")
        check_rfp = rfp_override or bench_rfp
        check_item = item_override or bench_item

    out_dir = compare.out_dir_for(pursuit)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Checking {vs.name} for mistakes ===")
    print(f"Expecting: RFP {check_rfp or '?'}, Item {check_item or '?'}, client {client}\n")
    pages = check.load_pages(vs)
    rules = yaml.safe_load(check.CHECKS_PATH.read_text(encoding="utf-8"))
    findings = {"errors": [], "check": []}
    if max_pages and len(pages) > max_pages:
        findings["errors"].append(f"{len(pages)} pages but the limit is {max_pages}")
    check.check_numbers(pages, "RFP", r"(?:RFP|INDOT)\s*#?\s*(2\d{3})\b", check_rfp, findings)
    check.check_numbers(pages, "Item", r"Item\s*#?\s*-?\s*0?(\d{1,2})\b", check_item, findings)
    check.check_clients(pages, client, rules.get("clients", []), findings)
    check.check_doubles(pages, findings)
    check.check_spelling(pages, rules.get("ok_words", []), findings)

    lines = [f"Mistake check: {vs.name} ({len(pages)} pages)", ""]
    if findings["errors"]:
        lines.append(f"ERRORS ({len(findings['errors'])}) - fix before sending:")
        lines += [f"  ! {f}" for f in findings["errors"]]
    else:
        lines.append("No errors found.")
    if findings["check"]:
        lines.append(f"\nCHECK THESE ({len(findings['check'])}):")
        lines += [f"  ? {f}" for f in findings["check"]]
    report_text = "\n".join(lines)
    print(report_text)
    check_path = out_dir / "mistake-check.txt"
    check_path.write_text(report_text, encoding="utf-8")

    print(f"\n=== Comparing against {pursuit}'s ranked competitor(s) ===")
    if against.lower() == "all":
        ranks = compare.available_ranks(bench_rfp, bench_item)
        if not ranks:
            sys.exit(f"No competitors found for {pursuit}")
    else:
        ranks = [int(against)]

    out_paths = [compare.run(pursuit, rank, str(vs)) for rank in ranks]

    print(f"\nDone. Everything for this pursuit is in {out_dir}")
    print(f"  {check_path}")
    for p in out_paths:
        print(f"  {p}")
    return out_dir


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Check an LOI for mistakes and compare it against ranked competitors, in one pass.")
    parser.add_argument("pursuit", help='e.g. "2605 Item 5" - which pursuit\'s '
                        "competitor data to benchmark against")
    parser.add_argument("--against", default="all",
                        help='competitor rank: 1 = winner, 2, 3, or "all" (default)')
    parser.add_argument("--vs", help="Path to a draft LOI, if it isn't filed "
                        "under reference/proposal-analysis/VS Proposals yet")
    parser.add_argument("--client", default="INDOT")
    parser.add_argument("--rfp", help="Override the RFP number the mistake "
                        "checker expects (only needed if it can't guess it "
                        "from the draft's filename)")
    parser.add_argument("--item", help="Override the item number the mistake "
                        "checker expects")
    parser.add_argument("--max-pages", type=int, help="Page limit, e.g. 12")
    args = parser.parse_args()

    try:
        review(args.pursuit, args.against, args.vs, args.client,
               args.rfp, args.item, args.max_pages)
    except compare.anthropic.AuthenticationError:
        sys.exit("API key is missing or wrong. Set it with:\n"
                 '  setx ANTHROPIC_API_KEY "sk-ant-..."\n'
                 "then open a new window. Keys: console.anthropic.com")
    except TypeError as exc:
        if "auth" in str(exc).lower():
            sys.exit("No API key set. Run:\n"
                     '  setx ANTHROPIC_API_KEY "sk-ant-..."\n'
                     "then open a new window. Keys: console.anthropic.com")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
