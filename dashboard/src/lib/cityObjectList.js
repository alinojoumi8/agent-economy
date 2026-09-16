export const CITY_LIST_PAGE_SIZE = 40;

export function cityObjectMatches(item, query = "") {
  const needle = query.trim().toLowerCase();
  return !needle || `${item.name} ${item.label} ${item.id} ${item.role || ""}`.toLowerCase().includes(needle);
}

export function cityObjectRows(model, society, visibleAgents, query = "") {
  const groups = [
    ["agent", "Person", visibleAgents], ["firm", "Business", model.firms],
    ["place", "Place", model.places], ["project", "Project", model.constructionProjects],
    ["household", "Household", society.households.available ? society.households.items : []],
    ["institution", "Bank", society.institutions.available ? society.institutions.items : []],
  ];
  return groups.flatMap(([kind, label, items]) => items.map(item => ({ kind, label, id: item.id,
    key: `${kind}:${item.id}`, name: item.name || `${label} #${item.id}`, role: item.role || "" })))
    .filter(item => cityObjectMatches(item, query));
}

export function cityObjectPage(rows, requestedPage) {
  const pages = Math.max(1, Math.ceil(rows.length / CITY_LIST_PAGE_SIZE));
  const page = Math.max(0, Math.min(Number.isSafeInteger(requestedPage) ? requestedPage : 0, pages - 1));
  return { page, pages, rows: rows.slice(page * CITY_LIST_PAGE_SIZE, (page + 1) * CITY_LIST_PAGE_SIZE) };
}
