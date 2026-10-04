"use client";

import type { RefObject } from "react";

import type { SessionMode } from "@/lib/use-elevenlabs-session";
import type { VisualCaptureStatus } from "@/lib/use-visual-capture";
import type { VisualEvent } from "@/lib/visual-observation-api";

/**
 * One visual input as this panel needs it.
 *
 * The video ref travels as its own prop rather than inside this object: React's
 * rules forbid reading a ref during render, and a props object that carries one
 * cannot be read at all without tripping that rule.
 */
export type VisualSourceView = {
  events: readonly VisualEvent[];
  error: string | null;
  status: VisualCaptureStatus;
  start: () => void;
  stop: () => void;
};

type VisualInputPanelProps = {
  screen: VisualSourceView;
  screenVideoRef: RefObject<HTMLVideoElement | null>;
  camera: VisualSourceView;
  cameraVideoRef: RefObject<HTMLVideoElement | null>;
  mode: SessionMode;
};

/**
 * The two visual inputs, each started and stopped on its own.
 *
 * This panel is rendered once for the whole workspace rather than inside the
 * Teach and Learn tabs. Two copies would mean two video elements competing for
 * one hook's ref, and switching tabs would tear down a live camera mid-session.
 */
export function VisualInputPanel({
  screen,
  screenVideoRef,
  camera,
  cameraVideoRef,
  mode,
}: VisualInputPanelProps) {
  const isScreenOn = isActive(screen.status);
  const isCameraOn = isActive(camera.status);
  const observations = [...screen.events, ...camera.events].sort(
    (first, second) =>
      Date.parse(first.occurred_at) - Date.parse(second.occurred_at),
  );

  return (
    <section className="screen-share-panel screen-share-main" aria-label="Visual input">
      <div className="screen-share-heading">
        <div>
          <span className="eyebrow">Visual input</span>
          <h1>
            {mode === "learning"
              ? "Show Metadosis how you work"
              : "Let Metadosis watch you practise"}
          </h1>
        </div>
        <div className="visual-source-states">
          <SourceState label="Screen" isOn={isScreenOn} status={screen.status} />
          <SourceState label="Camera" isOn={isCameraOn} status={camera.status} />
        </div>
      </div>

      <div className="visual-source-controls">
        <SourceToggle
          label="Share Screen"
          stopLabel="Stop screen"
          source={screen}
          isOn={isScreenOn}
        />
        <SourceToggle
          label="Enable Camera"
          stopLabel="Stop camera"
          source={camera}
          isOn={isCameraOn}
        />
      </div>

      <div className={`visual-stages${isScreenOn && isCameraOn ? " is-split" : ""}`}>
        <div className={`screen-stage${isScreenOn ? " is-active" : ""}`}>
          <video
            className={`screen-preview${isScreenOn ? " is-active" : ""}`}
            ref={screenVideoRef}
            muted
            playsInline
            aria-label="Shared screen preview"
          />
          {!isScreenOn && !isCameraOn && (
            <div className="screen-empty-state">
              <span className="eyebrow">Nothing shared yet</span>
              <h2>
                {mode === "learning"
                  ? "Share a screen, a camera, or both"
                  : "Turn on your camera to be coached"}
              </h2>
              <p>
                {mode === "learning"
                  ? "Share your screen for software work, or enable the camera to demonstrate something physical. Metadosis watches either one and asks why."
                  : "Metadosis compares what it sees against what the expert taught, and speaks up when it matters."}
              </p>
            </div>
          )}
        </div>

        <div
          className={`screen-stage camera-stage${isCameraOn ? " is-active" : ""}`}
          hidden={!isCameraOn}
        >
          <video
            className={`screen-preview${isCameraOn ? " is-active" : ""}`}
            ref={cameraVideoRef}
            muted
            playsInline
            aria-label="Camera preview"
          />
        </div>
      </div>

      {screen.error && (
        <p className="screen-share-error" role="alert">
          Screen: {screen.error}
        </p>
      )}
      {camera.error && (
        <p className="screen-share-error" role="alert">
          Camera: {camera.error}
        </p>
      )}

      {observations.length > 0 && (
        <div className="screen-events" aria-live="polite">
          <span>Visual observations</span>
          <ol>
            {observations.map((observation) => (
              <li
                className={`visual-event source-${observation.source}`}
                key={observation.event_id}
              >
                <time dateTime={observation.occurred_at}>
                  {formatEventTime(observation.occurred_at)}
                  <em>{observation.source === "camera" ? "camera" : "screen"}</em>
                </time>
                <p>{observation.summary}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

function SourceToggle({
  isOn,
  label,
  source,
  stopLabel,
}: {
  isOn: boolean;
  label: string;
  source: VisualSourceView;
  stopLabel: string;
}) {
  if (isOn) {
    return (
      <button className="screen-share-button stop" type="button" onClick={source.stop}>
        {stopLabel}
      </button>
    );
  }

  return (
    <button
      className="screen-share-button"
      type="button"
      onClick={source.start}
      disabled={source.status === "requesting"}
    >
      {source.status === "requesting" ? "Requesting…" : label}
    </button>
  );
}

function SourceState({
  isOn,
  label,
  status,
}: {
  isOn: boolean;
  label: string;
  status: VisualCaptureStatus;
}) {
  return (
    <span className={`screen-share-state state-${status}`}>
      {label}: {isOn ? "on" : "off"}
    </span>
  );
}

function isActive(status: VisualCaptureStatus): boolean {
  return status === "capturing" || status === "processing";
}

function formatEventTime(occurredAt: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(occurredAt));
}
