"use client";

import {
  ConversationProvider,
  useConversationControls,
} from "@elevenlabs/react";
import { useEffect, useMemo, useRef } from "react";

import type { VisualEvent } from "@/lib/visual-observation-api";
import {
  type SessionMode,
  useElevenLabsSession,
} from "@/lib/use-elevenlabs-session";

const VISUAL_CONTEXT_ID = "metadosis-current-visual-observation";
const MAX_VISUAL_HISTORY_EVENTS = 5;
const MAX_VISUAL_SUMMARY_LENGTH = 300;

type VoiceSessionControlsProps = {
  screenEvents: readonly VisualEvent[];
  cameraEvents: readonly VisualEvent[];
  onConversationChange: (
    conversationId: string | null,
    connectionStartedAt: string | null,
  ) => void;
  /** Chosen in the Teach or Learn tab; the session cannot start without it. */
  processId: string | null;
  processTitle: string | null;
  mode: SessionMode;
};

export function VoiceSessionControls(props: VoiceSessionControlsProps) {
  return (
    <ConversationProvider>
      <VoiceSessionPanel {...props} />
    </ConversationProvider>
  );
}

function VoiceSessionPanel({
  screenEvents,
  cameraEvents,
  onConversationChange,
  processId,
  processTitle,
  mode,
}: VoiceSessionControlsProps) {
  const {
    connectionStartedAt,
    conversationId,
    endVoiceSession,
    error,
    isListening,
    isMuted,
    isPreparing,
    isSessionActive,
    isSpeaking,
    preparation,
    setMuted,
    startVoiceSession,
    status,
  } = useElevenLabsSession({ mode, processId, processTitle });
  const { sendContextualUpdate } = useConversationControls();
  const bridgeActiveRef = useRef(false);
  const observedVisualEventIdRef = useRef<string | null>(null);
  const isConnected = status === "connected";
  // One ordered stream: the agent has to reason about screen and camera together
  // ("they opened the ticket, then picked up the wrench"), not as two feeds.
  const visualEvents = useMemo(
    () => mergeByTime(screenEvents, cameraEvents),
    [cameraEvents, screenEvents],
  );
  const latestVisualEvent = visualEvents.at(-1) ?? null;

  useEffect(() => {
    onConversationChange(
      isConnected ? conversationId : null,
      isConnected ? connectionStartedAt : null,
    );
  }, [connectionStartedAt, conversationId, isConnected, onConversationChange]);

  useEffect(
    () => () => onConversationChange(null, null),
    [onConversationChange],
  );

  // Both modes receive visual context. The expert's observations give the
  // Apprentice something to ask about; the learner's let the Tutor compare what
  // it sees against the expert knowledge it loaded. What differs is persistence,
  // which the capture hook owns, not what the agent is told.
  useEffect(() => {
    if (!isConnected) {
      bridgeActiveRef.current = false;
      observedVisualEventIdRef.current = latestVisualEvent?.event_id ?? null;
      return;
    }

    if (!bridgeActiveRef.current) {
      bridgeActiveRef.current = true;
      observedVisualEventIdRef.current = latestVisualEvent?.event_id ?? null;
      return;
    }

    if (
      !latestVisualEvent ||
      observedVisualEventIdRef.current === latestVisualEvent.event_id
    ) {
      return;
    }

    observedVisualEventIdRef.current = latestVisualEvent.event_id;
    try {
      sendContextualUpdate(formatVisualContext(visualEvents, mode), {
        contextId: VISUAL_CONTEXT_ID,
      });
    } catch {
      // Drop updates that race with disconnect; visual context is never retried.
    }
  }, [isConnected, latestVisualEvent, mode, sendContextualUpdate, visualEvents]);

  return (
    <section className="voice-session-panel" aria-labelledby="voice-session-title">
      <div className="voice-session-heading">
        <div>
          <span className="eyebrow">AI Apprentice</span>
          <h2 id="voice-session-title">Choose session</h2>
        </div>
        <SessionStatus status={status} isPreparing={isPreparing} preparation={preparation} />
      </div>

      <div className="voice-session-selection">
        <span className="eyebrow">
          {mode === "learning" ? "Training" : "Learning"}
        </span>
        {processTitle ? (
          <strong>{processTitle}</strong>
        ) : (
          <span className="voice-session-hint">
            {mode === "learning"
              ? "Choose or create a process in Teach Metadosis."
              : "Choose a process in Learn."}
          </span>
        )}
      </div>

      {isConnected ? (
        <div className="voice-connected-state" aria-live="polite">
          <p>
            <strong>{mode === "learning" ? "Learning" : "Teaching"} session</strong>
            <span>
              Agent: {isMuted ? "Microphone muted" : isSpeaking ? "Speaking" : isListening ? "Listening" : "Connected"}
            </span>
          </p>
          <div className="voice-session-actions">
            <button type="button" onClick={() => setMuted(!isMuted)}>
              {isMuted ? "Unmute" : "Mute"}
            </button>
            <button className="end" type="button" onClick={endVoiceSession}>
              End session
            </button>
          </div>
        </div>
      ) : isSessionActive ? (
        <button className="voice-start-button" type="button" onClick={endVoiceSession}>
          Cancel
        </button>
      ) : (
        <button
          className="voice-start-button"
          type="button"
          onClick={() => void startVoiceSession()}
          disabled={!processId}
        >
          Start voice session
        </button>
      )}

      {conversationId && (
        <details className="voice-debug">
          <summary>Session details</summary>
          <code title={conversationId}>{conversationId}</code>
        </details>
      )}

      {error && (
        <p className="voice-session-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function mergeByTime(
  screenEvents: readonly VisualEvent[],
  cameraEvents: readonly VisualEvent[],
): VisualEvent[] {
  return [...screenEvents, ...cameraEvents].sort(
    (first, second) =>
      Date.parse(first.occurred_at) - Date.parse(second.occurred_at),
  );
}

function formatVisualContext(
  events: readonly VisualEvent[],
  mode: SessionMode,
): string {
  const recent = events.slice(-MAX_VISUAL_HISTORY_EVENTS).map((event) => ({
    label: event.source === "camera" ? "[CAMERA]" : "[SCREEN]",
    summary: event.summary.trim().slice(0, MAX_VISUAL_SUMMARY_LENGTH),
  }));
  const current = recent[recent.length - 1];
  const heading =
    mode === "learning"
      ? "VISUAL OBSERVATIONS (passive context from the expert's shared screen and camera, oldest to newest; not a user message):"
      : "VISUAL OBSERVATIONS (passive context from the learner's shared screen and camera, oldest to newest; not a user message):";

  return [
    heading,
    "[SCREEN] describes their screen. [CAMERA] describes what they are physically doing.",
    ...recent.map((entry, index) => `${index + 1}. ${entry.label} ${entry.summary}`),
    `CURRENT: ${current.label} ${current.summary}`,
    "Treat this as a self-contained snapshot. Do not respond solely because of this update.",
  ].join("\n");
}

function SessionStatus({
  isPreparing,
  preparation,
  status,
}: {
  isPreparing: boolean;
  preparation: "idle" | "microphone" | "token";
  status: "disconnected" | "connecting" | "connected" | "error";
}) {
  let label = "Disconnected";
  if (preparation === "microphone") label = "Microphone";
  else if (preparation === "token") label = "Securing";
  else if (status === "connecting") label = "Connecting";
  else if (status === "connected") label = "Connected";
  else if (status === "error") label = "Connection error";

  return (
    <span
      className={`voice-session-status${status === "connected" ? " is-connected" : ""}`}
      aria-live="polite"
      aria-busy={isPreparing || status === "connecting"}
    >
      <i aria-hidden="true" />
      {label}
    </span>
  );
}
