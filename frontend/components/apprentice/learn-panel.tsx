"use client";

import {
  ArrowLeftIcon,
  ArrowRightIcon,
  WaveformIcon,
} from "@/components/apprentice/icons";
import { SourceControls } from "@/components/apprentice/source-controls";
import type {
  SessionView,
  VisualSourceView,
} from "@/components/apprentice/view-models";
import type { Process } from "@/lib/process-api";

const PRACTICE_STEPS: ReadonlyArray<{
  title: string;
  optional?: boolean;
  note: string;
}> = [
  { title: "Share your screen", note: "Metadosis will watch you work." },
  {
    title: "Enable camera",
    optional: true,
    note: "Useful for physical tasks or extra context.",
  },
  {
    title: "Start guided session",
    note: "Metadosis will coach you and give feedback in real time.",
  },
];

type LearnPanelProps = {
  hidden: boolean;
  processes: readonly Process[];
  selectedProcess: Process | null;
  isLoadingProcesses: boolean;
  processError: string | null;
  onSelectProcess: (processId: string) => void;
  onClearProcess: () => void;
  screen: VisualSourceView;
  camera: VisualSourceView;
  session: SessionView;
};

/**
 * Learning asks a different first question than teaching: not "what are you
 * showing me" but "what do you want to learn". The visual controls stay out of
 * the way until a process has been chosen.
 */
export function LearnPanel({
  camera,
  hidden,
  isLoadingProcesses,
  onClearProcess,
  onSelectProcess,
  processError,
  processes,
  screen,
  selectedProcess,
  session,
}: LearnPanelProps) {
  return (
    <section
      id="learn-panel"
      className="mode-panel"
      role="tabpanel"
      aria-labelledby="learn-tab"
      hidden={hidden}
    >
      {session.isLive ? (
        <>
          <header className="panel-intro is-live">
            <div>
              <span className="eyebrow">Learn from Metadosis</span>
              <h1 className="display display-sm">
                Learning: {selectedProcess?.title ?? "this process"}
              </h1>
              <p className="lede">
                Work through it yourself. Metadosis is watching and will step in
                when it helps.
              </p>
            </div>
            <span className="live-pill">
              <i aria-hidden="true" />
              Live
              <time>{session.clock ?? "00:00:00"}</time>
            </span>
          </header>
          <div className="live-sources">
            <SourceControls screen={screen} camera={camera} />
          </div>
        </>
      ) : selectedProcess ? (
        <>
          <button className="back-link" type="button" onClick={onClearProcess}>
            <ArrowLeftIcon />
            All processes
          </button>

          <header className="panel-intro">
            <span className="eyebrow">Practice this process</span>
            <h1 className="display">{selectedProcess.title}</h1>
            {selectedProcess.description && (
              <p className="lede">{selectedProcess.description}</p>
            )}
          </header>

          <div className="practice-grid">
            <ol className="practice-steps">
              {PRACTICE_STEPS.map((step, index) => (
                <li key={step.title}>
                  <span className="practice-index">{index + 1}</span>
                  <div>
                    <strong>
                      {step.title}
                      {step.optional && <em> — optional</em>}
                    </strong>
                    <p>{step.note}</p>
                  </div>
                </li>
              ))}
            </ol>

            <div className="practice-actions">
              <SourceControls screen={screen} camera={camera} />
              <button
                className="btn btn-primary btn-block btn-cta"
                type="button"
                onClick={session.isStarting ? session.cancel : session.start}
              >
                <span className="btn-badge" aria-hidden="true">
                  3
                </span>
                <WaveformIcon />
                {session.isStarting ? session.statusLabel : "Start guided session"}
              </button>
              <p className="step-hint">
                Metadosis will ask for microphone permission and speak with you.
              </p>
              {session.error && (
                <p className="form-error" role="alert">
                  {session.error}
                </p>
              )}
            </div>
          </div>
        </>
      ) : (
        <>
          <header className="panel-intro">
            <span className="eyebrow">Learn from Metadosis</span>
            <h1 className="display">What do you want to learn?</h1>
            <p className="lede">
              Practice real processes taught by experts. Metadosis will watch,
              coach you in real time, and help you build confidence.
            </p>
          </header>

          {isLoadingProcesses ? (
            <p className="step-note">Loading processes…</p>
          ) : processes.length === 0 ? (
            <p className="step-note">
              Nothing has been taught yet. Capture a process in Teach first.
            </p>
          ) : (
            <ul className="process-cards">
              {processes.map((process) => (
                <li key={process.id}>
                  <button
                    className="process-card"
                    type="button"
                    onClick={() => onSelectProcess(process.id)}
                  >
                    <span className="process-sigil" aria-hidden="true">
                      {process.title.trim().charAt(0).toUpperCase()}
                    </span>
                    <span className="process-card-text">
                      <strong>{process.title}</strong>
                      {process.description && <span>{process.description}</span>}
                    </span>
                    <ArrowRightIcon />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {processError && (
            <p className="form-error" role="alert">
              {processError}
            </p>
          )}
        </>
      )}
    </section>
  );
}
