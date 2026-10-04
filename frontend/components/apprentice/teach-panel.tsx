"use client";

import { WaveformIcon } from "@/components/apprentice/icons";
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

      {!session.isLive && (
        <>
          <header className="panel-intro">
            <span className="eyebrow">Teach Metadosis</span>
            <h1 className="display">
              {selectedProcess
                ? `Ready to teach: ${selectedProcess.title}`
                : "Pass on how you actually work."}
            </h1>
            <p className="lede">
              {selectedProcess
                ? "Metadosis will ask for microphone permission and talk with you while you work."
                : "Work normally. Metadosis watches, listens, and asks why when it matters."}
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

          <div className="teach-setup">
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

            <div className="teach-actions">
              <SourceControls screen={screen} camera={camera} />
              <button
                className="btn btn-primary btn-block btn-cta"
                type="button"
                onClick={session.isStarting ? session.cancel : session.start}
                disabled={!selectedProcess && !session.isStarting}
              >
                <span className="btn-badge" aria-hidden="true">
                  3
                </span>
                <WaveformIcon />
                {session.isStarting ? session.statusLabel : "Start voice session"}
              </button>
            </div>

            {!selectedProcess && (
              <p className="step-hint">Choose or create a process to begin.</p>
            )}
            {!isSharing && selectedProcess && (
              <p className="step-hint">
                Share your screen for software work, or enable the camera for physical tasks.
              </p>
            )}
            {session.error && (
              <p className="form-error" role="alert">
                {session.error}
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
