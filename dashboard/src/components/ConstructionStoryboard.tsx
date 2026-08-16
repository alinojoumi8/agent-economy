import { useId } from "react";

export type ConstructionVisualStage = "site" | "foundation" | "frame" | "shell" | "completed";

export const CONSTRUCTION_STAGES: Array<{
  key: Exclude<ConstructionVisualStage, "site">;
  label: string;
  description: string;
}> = [
  { key: "foundation", label: "Foundation", description: "Building has begun below one third of required work." },
  { key: "frame", label: "Frame", description: "At least one third of required work is stored." },
  { key: "shell", label: "Shell", description: "At least two thirds of required work is stored." },
  { key: "completed", label: "Complete", description: "All work is stored and the operational place exists." },
];

export function normalizeConstructionStage(value: string | null | undefined): ConstructionVisualStage {
  const stage = String(value || "").toLowerCase();
  if (stage === "completed") return "completed";
  if (stage === "shell") return "shell";
  if (stage === "frame") return "frame";
  if (stage === "foundation" || stage === "building") return "foundation";
  return "site";
}

export function constructionStageIndex(value: string | null | undefined) {
  const normalized = normalizeConstructionStage(value);
  return CONSTRUCTION_STAGES.findIndex(stage => stage.key === normalized);
}

type ConstructionStageArtProps = {
  stage: ConstructionVisualStage;
  compact?: boolean;
};

export function ConstructionStageArt({ stage, compact = false }: ConstructionStageArtProps) {
  const rawId = useId().replaceAll(":", "");
  const roofId = `roof-${rawId}`;
  const wallId = `wall-${rawId}`;
  const glowId = `glow-${rawId}`;
  const hasFoundation = stage !== "site";
  const hasFrame = ["frame", "shell", "completed"].includes(stage);
  const hasShell = ["shell", "completed"].includes(stage);
  const isComplete = stage === "completed";

  return <svg
    className={`world-os-construction-art${compact ? " world-os-construction-art--compact" : ""}`}
    viewBox="0 0 240 170"
    role="img"
    aria-label={`${stage} construction geometry`}
  >
    <defs>
      <linearGradient id={roofId} x1="0" y1="0" x2="1" y2="1">
        <stop stopColor="#60727b" /><stop offset="1" stopColor="#263740" />
      </linearGradient>
      <linearGradient id={wallId} x1="0" y1="0" x2="0" y2="1">
        <stop stopColor="#dbc7a7" /><stop offset="1" stopColor="#8d7a62" />
      </linearGradient>
      <radialGradient id={glowId} cx="50%" cy="50%" r="50%">
        <stop stopColor="#27d7dc" stopOpacity=".24" /><stop offset="1" stopColor="#27d7dc" stopOpacity="0" />
      </radialGradient>
    </defs>
    <ellipse cx="120" cy="128" rx="105" ry="35" fill={`url(#${glowId})`} />
    <path d="M19 117l94-53 109 56-97 46z" fill="#182725" stroke="#33504b" strokeWidth="2" />
    <path d="M35 117l79-43 90 46-81 37z" fill="#263533" stroke="#49615d" />
    <path d="M41 111l75-38 80 41-75 35z" fill="none" stroke="#5b7771" strokeDasharray="4 5" opacity={stage === "site" ? 1 : .35} />
    {stage === "site" && <>
      <path d="M66 113l52-27 55 29-53 25z" fill="#1c3736" stroke="#2ed7da" strokeWidth="2" strokeDasharray="6 4" />
      <path d="M118 86v54M66 113l107 2" stroke="#2ed7da" strokeWidth="1" opacity=".45" />
      <circle cx="119" cy="113" r="7" fill="#2ed7da" opacity=".75" />
    </>}
    {hasFoundation && <>
      <path d="M64 119l55-30 58 30-57 28z" fill="#858a82" stroke="#c8c7b9" strokeWidth="2" />
      <path d="M64 119v8l56 29 57-29v-8l-57 28z" fill="#4e5653" />
      <path d="M74 117l45-23 47 24-46 23z" fill="#b8b3a4" stroke="#73786f" />
      <path d="M91 107v29M119 94v47M145 107v28M74 117l92 1" stroke="#6f756d" strokeWidth="1" />
    </>}
    {hasFrame && <g fill="none" stroke="#d99646" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M75 117V68M119 141V88M166 118V67" />
      <path d="M75 68l44-24 47 23-47 22zM75 92l44-24 47 23M75 117l44-29 47 30" />
      <path d="M85 63l34-31 37 31M119 32v56" />
      <path d="M87 111V80M101 104V72M136 103V72M151 111V80" strokeWidth="2.5" />
    </g>}
    {hasShell && <>
      <path d="M75 69l44 21v51l-44-23z" fill={`url(#${wallId})`} stroke="#e0d2b8" />
      <path d="M119 90l47-23v51l-47 23z" fill="#9b896f" stroke="#d0bea0" />
      <path d="M75 69l44-37 47 35-47 23z" fill={`url(#${roofId})`} stroke="#9eabb1" strokeWidth="2" />
      <path d="M84 83l23 11v17L84 100zM132 91l21-10v18l-21 10z" fill="#223d48" stroke="#73b6c4" />
      <path d="M103 132v-24l14 7v23" fill="#5c493c" />
    </>}
    {isComplete && <>
      <path d="M73 69l46-39 50 37-3 5-47-34-43 36z" fill="#222f37" />
      <path d="M77 119l42 22 47-23v8l-47 24-42-22z" fill="#725e48" opacity=".7" />
      <g fill="#72d4c6"><circle cx="55" cy="111" r="9" /><circle cx="181" cy="109" r="10" /></g>
      <g fill="#425f43"><path d="M55 93l-15 20h30z" /><path d="M181 88l-17 24h34z" /></g>
      <g stroke="#263b2c" strokeWidth="4"><path d="M55 111v24M181 109v25" /></g>
      <path d="M123 146l17 9-28 13-17-9z" fill="#676c65" />
    </>}
  </svg>;
}

type ConstructionStoryboardProps = {
  stage: string;
  lifecycle: string;
};

export function ConstructionStoryboard({ stage, lifecycle }: ConstructionStoryboardProps) {
  const activeIndex = constructionStageIndex(stage);
  return <section className="world-os-construction-storyboard" aria-label="Construction storyboard">
    <header>
      <div>
        <p className="world-os-kicker">Stored work geometry</p>
        <h3>Construction storyboard</h3>
      </div>
      <span>{activeIndex < 0 ? `Lifecycle: ${lifecycle}` : `Current: ${CONSTRUCTION_STAGES[activeIndex].label}`}</span>
    </header>
    <div className="world-os-construction-stage-grid">
      {CONSTRUCTION_STAGES.map((item, index) => {
        const state = activeIndex < 0 ? "future" : index < activeIndex ? "passed" : index === activeIndex ? "current" : "future";
        return <article key={item.key} className={`world-os-construction-stage is-${state}`} data-stage={item.key}>
          <strong>{item.label}</strong>
          <ConstructionStageArt stage={item.key} compact />
          <span aria-hidden="true" />
          <small>{state === "passed" ? "Observed" : state === "current" ? "Current stage" : "Not reached"}</small>
        </article>;
      })}
    </div>
    <p>Stages are derived from committed work units. Unreached stages are reference geometry, not claimed progress.</p>
  </section>;
}
