"use client";

import type { ReactNode } from "react";

import { CheckIcon, WaveformIcon } from "@/components/apprentice/icons";
import { ProcessPicker } from "@/components/apprentice/process-picker";
import { SourceControls } from "@/components/apprentice/source-controls";
import {
  isVisualSourceActive,
  type SessionView,
  type VisualSourceView,
} from "@/components/apprentice/view-models";
import type { Process } from "@/lib/process-api";

type TeachPanelProps = {
  hidden: boolean;
  processes: readonly Process[];
  selectedProcess: Process | null;
  isLoadingProcesses: boolean;
  isCreatingProcess: boolean;
  processError: string | null;
  onSelectProcess: (processId: string) => void;
  onCreateProcess: (title: string) => Promise<void>;
  screen: VisualSourceView;
  camera: VisualSourceView;
  session: SessionView;
  /** Shown once after a session ends, then dismissed. */
  finishNotice: string | null;
  onDismissNotice: () => void;
};

/**
 * Teaching, as a sequence the expert can follow without being told where to
 * start: choose the process, show the work, start the apprentice. Once the
 * session is live the setup recedes and the shared view becomes the page.
 */
export function TeachPanel({
  camera,
  finishNotice,
  hidden,
  isCreatingProcess,
  isLoadingProcesses,
  onCreateProcess,
  onDismissNotice,
  onSelectProcess,
  processError,
  processes,
  screen,
  selectedProcess,
  session,
}: TeachPanelProps) {
  const isSharing =
    isVisualSourceActive(screen.status) || isVisualSourceActive(camera.status);
  // Once the expert is already sharing a view, the shared stage must sit right
  // below a short header rather than under the full step list — the 3-step
  // walkthrough is for setup, and setup is effectively done once there is
  // something to watch and someone to watch it for.
  const isReady = !session.isLive && isSharing && Boolean(selectedProcess);

  return (
    <section
      id="teach-panel"
      className="mode-panel"
      role="tabpanel"
      aria-labelledby="teach-tab"
      hidden={hidden}
    >
      {session.isLive && (
        <header className="panel-intro is-live">
          <div>
            <span className="eyebrow">Teach Metadosis</span>
            <h1 className="display display-sm">
              Teaching: {selectedProcess?.title ?? "your process"}
            </h1>
            <p className="lede">
              Work the way you normally would. Metadosis is listening and will ask
              why when something matters.
            </p>
          </div>
          <span className="live-pill">
            <i aria-hidden="true" />
            Live
            <time>{session.clock ?? "00:00:00"}</time>
          </span>
        </header>
      )}

      {session.isLive && (
        <div className="live-sources">
          {!isSharing && (
            <p className="step-hint">
              Share your screen or enable the camera so Metadosis can see the work.
            </p>
          )}
          <SourceControls screen={screen} camera={camera} />
        </div>
      )}

      {isReady && (
        <>
          <header className="panel-intro">
            <span className="eyebrow">Teach Metadosis</span>
            <h1 className="display display-sm">
              Ready to teach: {selectedProcess?.title}
            </h1>
            <p className="lede">
              Metadosis will ask for microphone permission and talk with you
              while you work.
            </p>
          </header>

          <div className="live-sources">
            <SourceControls screen={screen} camera={camera} />
          </div>

          <button
            className="btn btn-primary btn-block btn-cta"
            type="button"
            onClick={session.isStarting ? session.cancel : session.start}
          >
            <span className="btn-badge" aria-hidden="true">
              3
            </span>
            <WaveformIcon />
            {session.isStarting ? session.statusLabel : "Start voice session"}
          </button>
          {session.error && (
            <p className="form-error" role="alert">
              {session.error}
            </p>
          )}
        </>
      )}

      {!session.isLive && !isReady && (
        <>
          <header className="panel-intro is-wide">
            <span className="eyebrow">Teach Metadosis</span>
            <h1 className="display">Pass on how you actually work.</h1>
            <p className="lede">
              Teach is where an expert&rsquo;s know-how becomes something
              Metadosis can pass on. Pick the process, share your screen or
              camera so it can watch, then just work: Metadosis stays quiet
              and asks why only when a choice actually mattered. When you
              finish, what it captured becomes a Work Map the next person can
              learn from in the Learn tab.
            </p>
          </header>

          {finishNotice && (
            <div className="notice" role="status">
              <p>{finishNotice}</p>
              <button
                className="notice-dismiss"
                type="button"
                onClick={onDismissNotice}
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
          )}

          <ol className="steps">
            <Step
              index="01"
              eyebrow="Process"
              title="What are you teaching?"
              isDone={Boolean(selectedProcess)}
            >
              <ProcessPicker
                processes={processes}
                selectedProcess={selectedProcess}
                isLoading={isLoadingProcesses}
                isCreating={isCreatingProcess}
                isLocked={session.isStarting}
                error={processError}
                onSelect={onSelectProcess}
                onCreate={onCreateProcess}
              />
            </Step>

            <Step
              index="02"
              eyebrow="Visual input"
              title="Show Metadosis what you do."
              isDone={isSharing}
            >
              <p className="step-note">
                Share your screen for software work, or enable the camera for
                physical tasks.
              </p>
              <SourceControls screen={screen} camera={camera} />
            </Step>

            <Step index="03" eyebrow="Apprentice" title="Ready when you are.">
              <p className="step-note">
                Metadosis will ask for microphone permission and talk with you
                while you work.
              </p>
              <button
                className="btn btn-primary btn-block btn-cta"
                type="button"
                onClick={session.isStarting ? session.cancel : session.start}
                disabled={!selectedProcess && !session.isStarting}
              >
                <WaveformIcon />
                {session.isStarting ? session.statusLabel : "Start voice session"}
              </button>
              {!selectedProcess && (
                <p className="step-hint">Choose a process in step 01 to begin.</p>
              )}
              {session.error && (
                <p className="form-error" role="alert">
                  {session.error}
                </p>
              )}
            </Step>
          </ol>
        </>
      )}
    </section>
  );
}


function Step({
  children,
  eyebrow,
  index,
  isDone = false,
  title,
}: {
  children: ReactNode;
  eyebrow: string;
  index: string;
  isDone?: boolean;
  title: string;
}) {
  return (
    <li className="step">
      <span className="step-index">
        {isDone ? <CheckIcon /> : index}
        <span className="sr-only">
          Step {index}
          {isDone ? ", done" : ""}
        </span>
      </span>
      <div className="step-body">
        <span className="eyebrow">{eyebrow}</span>
        <h2 className="step-title">{title}</h2>
        {children}
      </div>
    </li>
  );
}
