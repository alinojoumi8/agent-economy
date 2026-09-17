import { childNeedsByCurrency } from "../lib/citySociety.js";
import { humanize } from "../lib/civicCity.js";
import "./city-society.css";

/** @param {any} props */
export function CitySocietyEvidence({ household, institution, requested, tick, reason, onPerson, personHref }) {
  if (!household && !institution) return <section className="civic-city__record" aria-label="Unavailable city record">
    <h3>{requested}</h3><p>{reason || "This identity has no visible record at the selected tick."}</p>
    <p>The selection is preserved. Choose another public object or change the historical tick.</p>
  </section>;
  const record = household || institution;
  return <div className="city-society-evidence">
    <div className="civic-city__identity"><div>
      <p>{household ? "Household" : "Public institution"}</p><h3>{record.name}</h3>
      <span>Observed at tick {tick}</span>
    </div></div>
    {household ? <>
      <section className="civic-city__record">
        <header><span>Recorded membership</span><b>{household.members.length} visible</b></header>
        <p>Core members only. This list does not establish the full household size or a shared residence.</p>
        <ul className="city-society-members">{household.members.map(member => <li key={member.agent_id}>
          {member.modeled_residence?.state === "outside"
            ? (personHref ? <a href={personHref(member.agent_id)}>Inspect {member.name}</a> : <strong>{member.name}</strong>)
            : <button type="button" onClick={() => onPerson(member.agent_id)}>Inspect {member.name}</button>}
          <span>{member.age_years} years · {humanize(member.role)} member</span>
          {member.modeled_residence && <small>
            {member.modeled_residence.state === "outside" ? "Outside the modeled economy" : "Local resident"}
            {` since tick ${member.modeled_residence.since_tick}`}
          </small>}
          {member.role === "dependent" && <small>Age band: {humanize(member.age_band)}</small>}
          <small>Member since tick {member.joined_tick}{member.guardian_agent_id != null
            ? ` · Recorded guardian #${member.guardian_agent_id}` : ""}</small>
          {member.legacy_dependents > 0 && <small>{member.legacy_dependents} legacy dependents recorded at origin; these are counts, not person identities.</small>}
        </li>)}</ul>
        <p>Age bands derive from recorded birth ticks, at 365 days per year. School age does not mean enrollment; an adult membership does not establish a partnership.</p>
      </section>
      <section className="civic-city__record">
        <header><span>Child needs</span><b>Tick {tick}</b></header>
        {household.child_needs.length ? <>
          <ul className="city-society-members">{household.child_needs.map(need => <li key={need.child_agent_id}>
            <strong>{household.members.find(member => member.agent_id === need.child_agent_id)?.name || `Person #${need.child_agent_id}`}</strong>
            <span>{need.purchased_units} / {need.required_units} {need.goods_sector} units purchased</span>
            <span>{need.spent_cents} {need.currency_code || "unspecified currency"} cents spent</span>
            <span>{need.care_required_minutes} care minutes required · {humanize(need.care_status)}</span>
            {need.care_delivered_minutes != null && <span>{need.care_delivered_minutes} care minutes delivered · {need.care_unmet_minutes} unmet</span>}
          </li>)}</ul>
          <dl className="civic-city__facts">{childNeedsByCurrency(household.child_needs).map(([currency, cents]) =>
            <div key={currency}><dt>Child purchases · {currency}</dt><dd>{cents} cents</dd></div>)}</dl>
          <p>Delivered care is shown only when recorded for this day. These purchases cover visible children for this day, not the household's total budget.</p>
        </> : <p>No child-needs record is available for the visible members at this tick. Spending and care delivered are unavailable.</p>}
      </section>
    </> : <>
      <div className="civic-city__activity civic-city__activity--place">
        <span>Public bank status</span><strong>{humanize(institution.status)}</strong>
        <small>Recorded failure boundary, as of tick {tick}</small>
      </div>
      <dl className="civic-city__facts"><div><dt>Currency</dt><dd>{institution.currency_code || "Not exposed"}</dd></div></dl>
      <section className="civic-city__record"><p>This lens exposes public bank identity and status. Reserves, deposits, capital, borrower records and lending terms are not exposed here. An open status is not a measure of solvency or liquidity.</p></section>
    </>}
  </div>;
}
