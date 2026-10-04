"use client";

import type { RefObject } from "react";

import { EyeIcon, ScreenIcon, SparkIcon } from "@/components/apprentice/icons";
import {
  isVisualSourceActive,
  mergeVisualEvents,
  type VisualSourceView,
} from "@/components/apprentice/view-models";
import type { AgentUtterance } from "@/lib/use-elevenlabs-session";

const MAX_LISTED_OBSERVATIONS = 8;

type VisualStageProps = {
  screen: VisualSourceView;
  screenVideoRef: RefObject<HTMLVideoElement | null>;
  camera: VisualSourceView;
  cameraVideoRef: RefObject<HTMLVideoElement | null>;
  /** True while a mode that does not use the stage is open, e.g. Brain. */
  offstage: boolean;
  /** What an idle stage does: disappear entirely, or hold a compact placeholder. */
  idleBehavior: "hide" | "placeholder";
  isLive: boolean;
  isSpeaking: boolean;
  agentUtterance: AgentUtterance | null;
};

/**
 * The shared screen and camera, and what Metadosis is making of them.
 *
 * Mounted exactly once for the whole workspace and never unmounted while a
 * capture runs. Two copies would mean two video elements competing for one
 * hook's ref, and unmounting mid-session would tear down a live stream. When a
 * mode that has no use for it is open, the stage is clipped out of view rather
 * than removed, so the browser keeps decoding frames for the capture loop.
 */
export function VisualStage({
  agentUtterance,
  camera,
  cameraVideoRef,
  idleBehavior,
  isLive,
  isSpeaking,
  offstage,
  screen,
  screenVideoRef,
}: VisualStageProps) {
  const isScreenOn = isVisualSourceActive(screen.status);
  const isCameraOn = isVisualSourceActive(camera.status);
  const isIdle = !isScreenOn && !isCameraOn;
  // With no stream running there is nothing to keep alive, so an unused stage
  // can leave the layout completely instead of being parked off-screen.
  const isRemoved = isIdle && (offstage || idleBehavior === "hide");
  const observations = mergeVisualEvents(screen.events, camera.events);
  const latest = observations.at(-1);

  return (
    <section
      className={`stage-mount${offstage && !isIdle ? " is-offstage" : ""}`}
      hidden={isRemoved}
      aria-label="Shared view"
    >
      {isIdle ? (
        <div className="stage stage-idle">
          <ScreenIcon />
          <strong>Nothing shared yet</strong>
          <span>Share your screen or enable the camera to begin.</span>
        </div>
      ) : (
        <div
          className={`stage${isLive ? " is-live" : ""}${
            isScreenOn && isCameraOn ? " is-split" : ""
          }`}
        >
          <div className={`stage-frame${isScreenOn ? "" : " is-empty"}`}>
            <video
              className={`stage-video${isScreenOn ? " is-active" : ""}`}
              ref={screenVideoRef}
              muted
              playsInline
              aria-label="Shared screen preview"
            />
          </div>
          <div
            className={`stage-frame stage-frame-camera${
              isCameraOn ? "" : " is-empty"
            }`}
            hidden={!isCameraOn}
          >
            <video
              className={`stage-video${isCameraOn ? " is-active" : ""}`}
              ref={cameraVideoRef}
              muted
              playsInline
              aria-label="Camera preview"
            />
          </div>

          {isLive && (
            <div className="stage-overlay" aria-live="polite">
              <EyeIcon />
              <div className="stage-overlay-text">
                <strong>Metadosis is watching</strong>
                <span>
                  {latest
                    ? `Observed: ${latest.summary}`
                    : "Waiting for something worth noticing."}
                </span>
              </div>
              <Waveform isActive={isSpeaking} />
            </div>
          )}
        </div>
      )}

      {isLive && agentUtterance && (
        <article className="agent-note">
          <SparkIcon />
          <div>
            <span className="eyebrow">Metadosis</span>
            <p>{agentUtterance.text}</p>
          </div>
        </article>
      )}

      {isLive && observations.length > 0 && (
        <details className="observation-log">
          <summary>Observed so far ({observations.length})</summary>
          <ol>
            {observations.slice(-MAX_LISTED_OBSERVATIONS).map((observation) => (
              <li
                className={`observation source-${observation.source}`}
                key={observation.event_id}
              >
                <time dateTime={observation.occurred_at}>
                  {formatEventTime(observation.occurred_at)}
                  <em>{observation.source}</em>
                </time>
                <p>{observation.summary}</p>
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function Waveform({ isActive }: { isActive: boolean }) {
  return (
    <span className={`waveform${isActive ? " is-active" : ""}`} aria-hidden="true">
      <i />
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

function formatEventTime(occurredAt: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(occurredAt));
}
