export function Panel({ title, eyebrow, action, className = "", children }) {
  return (
    <section className={`panel min-w-0 overflow-hidden ${className}`}>
      <div className="panel-header">
        <div className="min-w-0">
          {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
          <h2 className="truncate text-sm font-semibold tracking-wide text-slate-100">{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function SectionTitle({ index, title, description }) {
  return (
    <div className="col-span-full mt-5 flex items-end gap-4 first:mt-0">
      <div>
        <div className="eyebrow">{String(index).padStart(2, "0")} / Observatory</div>
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-100">{title}</h2>
      </div>
      <div className="mb-2 hidden h-px flex-1 bg-mint-300/10 md:block" />
      <p className="mb-0.5 hidden max-w-xl text-right text-xs leading-relaxed text-slate-500 lg:block">{description}</p>
    </div>
  );
}

export function Empty({ children, text = "Nothing recorded yet." }) {
  return <div className="p-5 text-sm leading-relaxed text-slate-500">{children ?? text}</div>;
}

export function Badge({ children, tone = "neutral" }) {
  const tones = {
    neutral: "border-mint-300/15 bg-mint-300/[.04] text-slate-400",
    good: "border-mint-300/25 bg-mint-300/[.08] text-mint-300",
    warn: "border-gold-300/25 bg-gold-300/[.08] text-gold-300",
    bad: "border-coral-300/25 bg-coral-300/[.08] text-coral-300",
  };
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${tones[tone]}`}>{children}</span>;
}

export function Modal({ title, onClose, children, wide = false }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={event => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className={`modal ${wide ? "!w-[min(100%,1180px)]" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="flex items-center justify-between border-b border-mint-300/10 px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button className="button" onClick={onClose} aria-label={`Close ${title}`}>Close</button>
        </header>
        <div className="scrollbar max-h-[calc(90vh-4rem)] overflow-y-auto p-4">{children}</div>
      </section>
    </div>
  );
}
