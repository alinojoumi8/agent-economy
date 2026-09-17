import { useState } from "react";
import { cityObjectPage } from "../lib/cityObjectList.js";
import "./city-object-list.css";

/** @param {any} props */
export function CityObjectList({ rows, state, tick, query, onQuery, onSelect, onOpenEvidence, disabled }) {
  const [page, setPage] = useState(0);
  const visible = cityObjectPage(rows, page);
  return <section className="city-object-list" aria-label="Public city object list">
    <header><div><strong>Public city objects</strong><span>Tick {tick} · {rows.length} matching records</span></div>
      <label>Search city objects<input type="search" value={query} disabled={disabled}
        onChange={event => { setPage(0); onQuery(event.target.value); }} /></label></header>
    <ul>{visible.rows.map(item => <li key={item.key}>
      <button type="button" disabled={disabled} aria-pressed={String(state?.[item.kind]) === String(item.id)}
        onClick={() => {
          onSelect({ [item.kind]: item.id });
          if (window.matchMedia("(max-width: 980px)").matches) requestAnimationFrame(onOpenEvidence);
        }}>
        <strong>{item.name}</strong><span>{item.label} · #{item.kind === "institution" ? String(item.id).split(":")[1] : item.id}</span>
      </button>
    </li>)}</ul>
    {!rows.length && <p>No public city objects match this view and search.</p>}
    <footer><button type="button" disabled={disabled || visible.page === 0} onClick={() => setPage(visible.page - 1)}>Previous objects</button>
      <span>Page {visible.page + 1} of {visible.pages}</span>
      <button type="button" disabled={disabled || visible.page + 1 === visible.pages} onClick={() => setPage(visible.page + 1)}>Next objects</button>
      <button type="button" disabled={disabled} onClick={onOpenEvidence}>Open selected evidence</button></footer>
  </section>;
}
