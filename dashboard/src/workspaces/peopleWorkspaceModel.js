export const AGENT_PAGE_SIZE = 36;

/** A co-owner or guardian can follow a project without becoming its founder. */
export function projectInvolvesAgent(project, agentId) {
  return agentId != null && (project?.owner_agent_id === agentId
    || project?.steward_agent_id === agentId
    || (Array.isArray(project?.beneficial_owner_ids) && project.beneficial_owner_ids.includes(agentId)));
}

/** The agent the journey pane opens on when the URL names none. */
export function featuredAgentId(agents, projects) {
  const list = Array.isArray(agents) ? agents : [];
  const streams = Array.isArray(projects) ? projects : [];
  const constructionOwner = streams.find(project => (
    project?.kind === "construction"
    && project?.status === "active"
    && project?.owner_agent_id != null
  ))?.owner_agent_id;
  if (constructionOwner != null) return constructionOwner;
  const constructionSteward = streams.find(project => project?.kind === "construction"
    && project?.status === "active" && project?.steward_agent_id != null)?.steward_agent_id;
  if (constructionSteward != null) return constructionSteward;
  const runtimeAgent = list.find(agent => agent?.runtime);
  if (runtimeAgent) return runtimeAgent.id;
  const progressingOwner = streams.find(project => (
    project?.status === "active" && project?.owner_agent_id != null
  ))?.owner_agent_id;
  return progressingOwner ?? list[0]?.id ?? null;
}

/**
 * The journey pane follows the URL when it names an agent. Otherwise it keeps the
 * agent pinned on first choice for as long as that agent is still listed, so live
 * polling cannot swap the pane while the reader is on it.
 */
export function resolveSelectedAgentId({ requestedId, pinnedId, featuredId, agents }) {
  if (requestedId != null && Number.isFinite(requestedId)) return requestedId;
  const list = Array.isArray(agents) ? agents : [];
  if (pinnedId != null && list.some(agent => agent?.id === pinnedId)) return pinnedId;
  return featuredId ?? null;
}

/**
 * Page the list to the selection only when the selection changed (or first became
 * locatable). Data refreshes for an unchanged selection return null, so a reader
 * who paged away is not snapped back by polling.
 */
export function agentPageForSelection({ selectedId, visibleAgents, pageSize = AGENT_PAGE_SIZE, pagedFor }) {
  if (selectedId == null || pagedFor === selectedId) return null;
  const index = (Array.isArray(visibleAgents) ? visibleAgents : [])
    .findIndex(agent => agent?.id === selectedId);
  return index >= 0 ? Math.floor(index / pageSize) : null;
}
