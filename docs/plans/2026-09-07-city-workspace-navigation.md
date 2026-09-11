# City workspace navigation and layout

This implements the remaining desktop layout, mobile object list, breadcrumb and
event-bookmark controls in W4. It does not complete W5–W9 or prove the full price
discovery workflow against a real research campaign. Goods and equity remain
equally primary research domains.

## Behavior

- In the World OS City workspace, the map occupies at least 65% of the visible
  main workspace at 1280×900 and 1440×1000, with its inspector open. The test
  includes workspace padding and controls in its denominator. The application
  navigation rail and global header are outside that workspace.
  The compact toolbar begins at 1200 pixels; smaller windows retain stacked
  controls so the navigation and details buttons stay within the viewport.
- City details, evidence instrumentation and filters are collapsible. Camera and
  follow controls occupy the inspector rail so they cannot intercept map objects.
- Atlas, Diorama, recorded day and List share the existing observer cursor and
  selection. `view=list` is a canonical, reloadable URL state. List search covers
  public people, firms, places, projects, visible households and public banks;
  pagination limits the rendered list to 40 records at a time.
- Mobile List uses 44-pixel controls and opens the existing evidence sheet on
  selection, including keyboard activation. Breadcrumbs link a person to their
  recorded visible household and a business to its projected workplace. They
  do not infer missing relationships or create a second inspector.
- Save observation freezes the displayed tick, even when observing live mode.
  Save event bookmark additionally retains the selected public event ID.
  Restoring changes observer navigation only. Return to live city remains
  available when a historical frame fails to load.

## Persistence and privacy

Bookmarks use the existing `saved_views` table in the separate operator SQLite
workspace. They never write to the world database or persistent browser storage.
Each operator/run/fork/view-key/policy/semantics/projection context has at most 20
distinct observations. Explicitly saving an existing observation moves it first;
capacity exhaustion asks the operator to remove an entry and never evicts one.

The saved strings contain only numeric tick, fork, object/event identifiers,
camera, follow, layer, population, view and operator-entered search/filter state.
Event payloads, entity details, transcripts and credentials are not copied.
The server independently bounds and validates every field and rejects foreign
context, future ticks, multiple selected objects and unsupported URL parameters.
The client additionally requires a canonical observer-state round trip before
using a saved record. The server normalizes field order, URL encoding and camera
precision; shared Python/JavaScript examples bind that serialization contract.

`GET /api/v2/operator/city-observations?context=<JSON>` returns
`{context, version, entries}`. Context contains `run_id`, `fork_id`, `view_key`,
`policy_version`, `semantics_version` and `projection_version`, taken from the
map envelope. An absent set has version 0. `PUT` accepts
`{context, expected_version, entries}` and requires the existing operator-session
CSRF token. It atomically checks the version, writes the set and appends an
operator audit reference. The audit contains no bookmark text.
Successful API responses carry `Cache-Control: private, no-store`.

These routes use the existing trusted local operator identity header and return
404 in hosted-safe mode. They are not a new remote authentication mechanism.
Writes return 403 for missing CSRF, 409 for context/version conflicts and 422 for
invalid fields. Conflict recovery explicitly reloads the saved set; it never
silently retries an overwrite. Responses from an earlier city context cannot
populate a newly selected fork. Failed reads/writes remain visible beside the
bookmark controls, and normal city navigation remains available.

## Review evidence

The images use synthetic browser fixtures; they demonstrate layout and controls,
not economic validity or performance at research scale.

- [Previous desktop layout](../research/assets/city-workspace-before.png)
- [Desktop map and inspector](../research/assets/city-workspace-desktop.png)
- [Mobile public-object list](../research/assets/city-workspace-mobile-list.png)

Focused API/store tests verify persistence, ownership, CSRF, context admission,
conflicts, invalid-field rejection, hosted refusal and unchanged world tables.
Browser checks exercise bookmark restore/reload/removal, failed writes, concurrent
edits, stale responses, map hit targets, the area threshold and mobile keyboard
selection. Final executed results are recorded in the implementation log.
