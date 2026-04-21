

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.core import HomeAssistant, callback


@callback
def get_default_agent(hass: HomeAssistant) -> conversation.default_agent.DefaultAgent:

    from homeassistant.components.conversation.agent_manager import async_get_agent
    from homeassistant.components.conversation.const import HOME_ASSISTANT_AGENT

    agent = async_get_agent(hass, HOME_ASSISTANT_AGENT)
    if agent is None:
        raise ValueError("No default conversation agent available")
    return agent


def convert_agent_info_to_dict(
    hass: HomeAssistant, agents_info: list[conversation.AgentInfo]
) -> dict[str, str]:

    result: dict[str, str] = {}
    entity_id_to_name = {}
    name_to_entity_id = {}

    for entity_id in hass.states.async_entity_ids("conversation"):
        state = hass.states.get(entity_id)
        if state:
            friendly_name = state.attributes.get("friendly_name", entity_id.split(".")[-1])
            entity_id_to_name[entity_id] = friendly_name
            name_to_entity_id[friendly_name] = entity_id

    for agent_info in agents_info:
        try:
            agent = conversation.agent_manager.async_get_agent(hass, agent_info.id)
            agent_id = agent_info.id

            if hasattr(agent, "registry_entry"):
                agent_id = agent.registry_entry.entity_id

            if agent_id in entity_id_to_name:
                result[agent_id] = entity_id_to_name[agent_id]
            elif agent_info.name in name_to_entity_id:
                entity_id = name_to_entity_id[agent_info.name]
                result[entity_id] = agent_info.name
            else:
                result[agent_id] = agent_info.name
        except Exception:
            if agent_info.name in name_to_entity_id:
                entity_id = name_to_entity_id[agent_info.name]
                result[entity_id] = agent_info.name
            else:
                result[agent_info.id] = agent_info.name

    return result
