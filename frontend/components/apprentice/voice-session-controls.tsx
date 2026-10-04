"use client";

import {
  ConversationProvider,
  useConversationControls,
} from "@elevenlabs/react";
import { useEffect, useRef } from "react";

import type { ScreenEvent } from "@/lib/screen-observation-api";
import {
  type SessionMode,
  useElevenLabsSession,
} from "@/lib/use-elevenlabs-session";

const SCREEN_CONTEXT_ID = "metadosis-current-screen-observation";
const MAX_SCREEN_HISTORY_EVENTS = 5;
const MAX_SCREEN_SUMMARY_LENGTH = 300;

type VoiceSessionControlsProps = {
  screenEvents: readonly ScreenEvent[];
  onConversationIdChange: (conversationId: string | null) => void;
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
  onConversationIdChange,
  processId,
  processTitle,
  mode,
}: VoiceSessionControlsProps) {
  const {
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
  const observedScreenEventIdRef = useRef<string | null>(null);
  const isConnected = status === "connected";
  const latestScreenEvent = screenEvents.at(-1) ?? null;

  useEffect(() => {
    onConversationIdChange(isConnected ? conversationId : null);
  }, [conversationId, isConnected, onConversationIdChange]);

  useEffect(
    () => () => onConversationIdChange(null),
    [onConversationIdChange],
  );

  useEffect(() => {
    const bridgeActive = isConnected && mode === "learning";
    if (!bridgeActive) {
      bridgeActiveRef.current = false;
      observedScreenEventIdRef.current = latestScreenEvent?.event_id ?? null;
      return;
    }

    if (!bridgeActiveRef.current) {
      bridgeActiveRef.current = true;
      observedScreenEventIdRef.current = latestScreenEvent?.event_id ?? null;
      return;
    }

    if (
      !latestScreenEvent ||
      observedScreenEventIdRef.current === latestScreenEvent.event_id
    ) {
      return;
    }

    observedScreenEventIdRef.current = latestScreenEvent.event_id;
    try {
      const context = formatScreenContext(screenEvents);
      sendContextualUpdate(context, { contextId: SCREEN_CONTEXT_ID });
    } catch {
      // Drop updates that race with disconnect; screen context is never retried.
    }
  }, [isConnected, latestScreenEvent, mode, screenEvents, sendContextualUpdate]);

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

function formatScreenContext(events: readonly ScreenEvent[]): string {
  const recent = events
    .slice(-MAX_SCREEN_HISTORY_EVENTS)
    .map((event) => event.summary.trim().slice(0, MAX_SCREEN_SUMMARY_LENGTH));
  const current = recent[recent.length - 1];
  return [
    "SCREEN OBSERVATIONS (passive context from the expert's shared screen, oldest to newest; not a user message):",
    ...recent.map((summary, index) => `${index + 1}. ${summary}`),
    `CURRENT: ${current}`,
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
