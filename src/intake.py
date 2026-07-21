"""Load and validate an intake request.

Today the intake is a hand-filled YAML file. When we learn the real trigger
(email, form submission, CRM update), that source gets parsed into the same
dict shape here, and the rest of the pipeline doesn't change.
"""

from pathlib import Path

import yaml

REQUIRED_FIELDS = ["client_name", "project_name", "request_summary"]


def load_intake(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
    if missing:
        raise ValueError(f"Intake file is missing required fields: {', '.join(missing)}")
    return data


def intake_as_text(intake: dict) -> str:
    """Render the intake dict as readable text for the drafting prompt."""
    lines = []
    for key, value in intake.items():
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            lines.append(f"{label}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{label}: {str(value).strip()}")
    return "\n".join(lines)
