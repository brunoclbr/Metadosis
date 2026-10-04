"use client";

export type WorkspaceMode = "teach" | "learn" | "brain";

const MODES: ReadonlyArray<{
  id: WorkspaceMode;
  index: string;
  label: string;
  summary: string;
}> = [
  { id: "teach", index: "01", label: "Teach", summary: "Capture expertise" },
  { id: "learn", index: "02", label: "Learn", summary: "Practice the process" },
  { id: "brain", index: "03", label: "Brain", summary: "Explore knowledge" },
];

/** The three product modes. Numbered because they are also the order in which
 * knowledge moves through Metadosis: captured, practised, then looked up. */
export function ModeNav({
  mode,
  onChange,
}: {
  mode: WorkspaceMode;
  onChange: (mode: WorkspaceMode) => void;
}) {
  return (
    <nav className="mode-nav" aria-label="Metadosis modes" role="tablist">
      {MODES.map((entry) => (
        <button
          id={`${entry.id}-tab`}
          className={`mode-tab${mode === entry.id ? " is-active" : ""}`}
          key={entry.id}
          type="button"
          role="tab"
          aria-controls={`${entry.id}-panel`}
          aria-selected={mode === entry.id}
          onClick={() => onChange(entry.id)}
        >
          <span className="mode-tab-index">{entry.index}</span>
          <span className="mode-tab-text">
            <strong>{entry.label}</strong>
            <span>{entry.summary}</span>
          </span>
        </button>
      ))}
    </nav>
  );
}
