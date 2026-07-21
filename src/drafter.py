"""Draft narrative proposal sections with the Claude API.

Only sections marked `mode: ai` in config.yaml come through here. The prompt
grounds Claude in the intake data and the boilerplate library so it writes
from real facts instead of inventing company details.
"""

import anthropic

SYSTEM_PROMPT = """\
You are a proposal writer for {company_name}, a civil engineering firm.
You draft sections of pre-proposals (short preliminary proposals sent to
prospective clients before a full fee proposal).

Rules:
- Write in a professional, confident, plainspoken tone. No marketing fluff.
- Use ONLY facts from the intake request and company boilerplate provided.
  Never invent project experience, staff names, certifications, or fees.
- If information needed for the section is missing from the intake, write
  [CONFIRM: <what's needed>] inline so a human reviewer catches it.
- Output plain paragraphs (and simple "- " bullet lists where natural).
  No markdown headings — the section title is added by the template.
"""

# Per-section drafting instructions. Tune these with real examples from
# past proposals after the meeting.
SECTION_INSTRUCTIONS = {
    "cover_letter": (
        "Write a brief cover letter (3 short paragraphs max) addressed to the "
        "client contact: thank them for the opportunity, name the project, and "
        "state that the attached pre-proposal outlines our understanding and "
        "proposed services. Close with enthusiasm for the project."
    ),
    "project_understanding": (
        "Write a 'Project Understanding' section: restate the client's project "
        "and goals in our own words, demonstrating we understood the request, "
        "including any site challenges or constraints mentioned."
    ),
    "scope_of_services": (
        "Write a 'Scope of Services' section: a short intro sentence, then a "
        "bullet list of the services requested, each with one sentence on what "
        "it covers for this specific project."
    ),
}

DEFAULT_INSTRUCTION = "Write the '{title}' section of the pre-proposal."


def draft_section(
    client: anthropic.Anthropic,
    model: str,
    company_name: str,
    section: dict,
    intake_text: str,
    library_text: str,
) -> str:
    instruction = SECTION_INSTRUCTIONS.get(
        section["id"], DEFAULT_INSTRUCTION.format(title=section["title"])
    )
    user_prompt = (
        f"<intake_request>\n{intake_text}\n</intake_request>\n\n"
        f"<company_boilerplate>\n{library_text}\n</company_boilerplate>\n\n"
        f"{instruction}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT.format(company_name=company_name),
        messages=[{"role": "user", "content": user_prompt}],
    )
    return next(b.text for b in response.content if b.type == "text").strip()


def draft_section_dry_run(section: dict) -> str:
    return (
        f"[DRY RUN — '{section['title']}' would be drafted by Claude here, "
        "using the intake request and content library as context.]"
    )
