"""Load boilerplate snippets from the content library.

The library is a folder of Markdown files. If the meeting reveals the real
source is SharePoint, past proposals, or a database, add a loader here that
pulls from that source into the same {name: text} shape.
"""

import re
from pathlib import Path

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "content_library"

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def load_snippet(filename: str) -> str:
    text = (LIBRARY_DIR / filename).read_text(encoding="utf-8")
    return _COMMENT_RE.sub("", text).strip()


def load_all_snippets() -> dict[str, str]:
    return {p.name: load_snippet(p.name) for p in sorted(LIBRARY_DIR.glob("*.md"))}
