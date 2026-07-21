"""Pre-proposal pipeline orchestrator.

Usage:
    python -m src.main intake\\sample_request.yaml --dry-run
    python -m src.main intake\\sample_request.yaml
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import document, drafter, intake, library

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a pre-proposal draft.")
    parser.add_argument("intake_file", help="Path to the intake YAML file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the Claude API; insert placeholders for AI sections",
    )
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    company_name = config["company"]["name"]

    request = intake.load_intake(args.intake_file)
    intake_text = intake.intake_as_text(request)
    snippets = library.load_all_snippets()
    library_text = "\n\n---\n\n".join(snippets.values())

    client = None
    if not args.dry_run:
        import anthropic

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY / ant profile

    sections: list[tuple[str, str]] = []
    for section in config["sections"]:
        print(f"  {section['title']} ({section['mode']})...")
        if section["mode"] == "boilerplate":
            body = library.load_snippet(section["source"])
        elif args.dry_run:
            body = drafter.draft_section_dry_run(section)
        else:
            body = drafter.draft_section(
                client, config["model"], company_name, section, intake_text, library_text
            )
        sections.append((section["title"], body))

    slug = re.sub(r"[^a-z0-9]+", "-", request["client_name"].lower()).strip("-")
    out_path = ROOT / "output" / f"preproposal_{slug}_{datetime.now():%Y%m%d_%H%M}.docx"
    document.build_document(company_name, request, sections, out_path)

    print(f"\nDone: {out_path}")
    print("Review the draft before sending — AI sections may contain [CONFIRM: ...] flags.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
