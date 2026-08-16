type LivingAgentPortraitProps = {
  agentId: number;
  name: string;
  large?: boolean;
};

const SKIN_TONES = ["#f2c7a5", "#d9a27f", "#b97c5d", "#8c5841", "#6c4434"];
const HAIR_TONES = ["#161717", "#30231e", "#4b3124", "#6b4b38", "#202a35"];
const CLOTHING_TONES = ["#267e87", "#375d9e", "#7e4d83", "#3d7758", "#9a6636", "#5f6578"];

/** Decorative, deterministic portraits. They never encode private agent traits. */
export function LivingAgentPortrait({ agentId, name, large = false }: LivingAgentPortraitProps) {
  const seed = Math.abs(Number(agentId) || 0);
  const skin = SKIN_TONES[seed % SKIN_TONES.length];
  const hair = HAIR_TONES[(seed * 3 + 1) % HAIR_TONES.length];
  const clothing = CLOTHING_TONES[(seed * 5 + 2) % CLOTHING_TONES.length];
  const hairVariant = seed % 4;
  const glasses = seed % 5 === 0;

  return <span
    className={`world-os-agent-portrait${large ? " world-os-agent-portrait--large" : ""}`}
    aria-hidden="true"
    title={`${name} decorative portrait`}
  >
    <svg viewBox="0 0 80 96" focusable="false">
      <rect width="80" height="96" rx="14" fill="#14201f" />
      <circle cx="63" cy="18" r="23" fill={clothing} opacity=".22" />
      <path d="M9 96c2-21 13-33 31-33s29 12 31 33" fill={clothing} />
      <path d="M28 62h24v14c-3 5-7 7-12 7s-9-2-12-7z" fill={skin} />
      <ellipse cx="40" cy="42" rx="21" ry="25" fill={skin} />
      {hairVariant === 0 && <path d="M18 42c0-25 11-32 24-32 16 0 23 12 22 31-7-3-12-9-15-16-7 9-17 14-31 17z" fill={hair} />}
      {hairVariant === 1 && <path d="M18 43c-2-22 8-34 23-34 18 0 25 14 22 35l-7-17c-11 7-23 9-38 8z" fill={hair} />}
      {hairVariant === 2 && <><path d="M18 42c0-21 8-32 22-32 15 0 24 11 24 32-7-10-15-15-24-15-9 0-16 5-22 15z" fill={hair} /><circle cx="20" cy="29" r="8" fill={hair} /><circle cx="59" cy="28" r="8" fill={hair} /></>}
      {hairVariant === 3 && <path d="M19 39c1-20 9-29 22-29 14 0 22 10 23 30-6-8-15-12-26-12-8 0-14 4-19 11z" fill={hair} />}
      <path d="M27 43c3-2 6-2 9 0M44 43c3-2 6-2 9 0" fill="none" stroke="#2b2522" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="32" cy="45" r="1.5" fill="#252323" />
      <circle cx="49" cy="45" r="1.5" fill="#252323" />
      <path d="M36 55c3 2 6 2 9 0" fill="none" stroke="#8b5147" strokeWidth="1.6" strokeLinecap="round" />
      {glasses && <g fill="none" stroke="#536b72" strokeWidth="1.4"><rect x="24" y="39" width="14" height="11" rx="4" /><rect x="43" y="39" width="14" height="11" rx="4" /><path d="M38 44h5" /></g>}
      <path d="M27 75l13 9 13-9 7 21H20z" fill="#f3f1e8" opacity=".18" />
    </svg>
  </span>;
}
