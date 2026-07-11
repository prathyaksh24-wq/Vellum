from __future__ import annotations


def build_learn_prompt(source: str, focus: str = "") -> str:
    clean_source = source.strip()
    if not clean_source:
        raise ValueError("learn source is required")
    focus_line = f"Focus specifically on: {focus.strip()}\n" if focus.strip() else ""
    return f"""Learn a reusable Vellum skill from this source:
{clean_source}
{focus_line}
Gather the source with existing tools appropriate to its type: read_file/list_files for approved local material, web_extract for a public URL, or the current conversation for a demonstrated procedure.

Author a Hermes-compatible SKILL.md with a concise description (60 characters or fewer) and this section order:
# Skill Title
## When to Use
## Quick Reference (only when useful)
## Procedure
## Pitfalls
## Verification

Use progressive disclosure: keep the common procedure in SKILL.md and put large supporting material in relative references/, templates/, scripts/, or assets/ files. Do not invent commands, APIs, or capabilities that were not verified from the source. Do not copy secrets, personal identifiers, raw private-folder content, or machine paths into the reusable skill. Generalize private local procedures before authoring.

Validate trigger and when-not-to-use guidance. Finish by calling skill_manage(action="create", skill_md=<complete SKILL.md>, category=<slug>). This stages the package in the user's approval queue. Use skill_manage(action="write_file") for support files only after creation is approved.
""".strip()
