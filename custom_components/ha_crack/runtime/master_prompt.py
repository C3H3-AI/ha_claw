

from __future__ import annotations

from .skill_store import (
    load_homeassistant_priority_skill_block,
    load_master_prompt,
    load_relevant_skill_prompt_blocks,
    load_runtime_prompt_doc,
    load_skill_catalog_prompt,
)


def build_master_prompt_sections(*, user_text: str = "") -> tuple[str, ...]:

    sections: list[str] = []

    priority_skill_block = load_homeassistant_priority_skill_block()
    if priority_skill_block:
        sections.append(priority_skill_block)

    master_prompt = load_master_prompt()
    if master_prompt:
        sections.append(master_prompt)

    memory_routing_guidance = load_runtime_prompt_doc("memory_routing")
    if memory_routing_guidance:
        sections.append(memory_routing_guidance)

    relevant_skill_blocks = load_relevant_skill_prompt_blocks(user_text)
    if relevant_skill_blocks:
        sections.append(f"## Relevant Installed Skills\n{relevant_skill_blocks}")
    else:
        skill_catalog = load_skill_catalog_prompt(exclude_homeassistant_priority=True)
        if skill_catalog:
            sections.append(f"## Installed Skill Index\n{skill_catalog}")

    return tuple(section for section in sections if section.strip())


def apply_master_prompt_layers(base_prompt: str, *, user_text: str = "") -> str:

    sections = [base_prompt, *build_master_prompt_sections(user_text=user_text)]
    return "\n\n".join(section for section in sections if section.strip())
