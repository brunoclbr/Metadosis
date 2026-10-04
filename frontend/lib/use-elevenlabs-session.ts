"use client";

import {
  useConversationControls,
  useConversationInput,
  useConversationMode,
  useConversationStatus,
} from "@elevenlabs/react";
import { useCallback, useEffect, useRef, useState } from "react";

export type SessionMode = "learning" | "teaching";

type PreparationState = "idle" | "microphone" | "token";

/** The last thing Metadosis said out loud, so the UI can show it alongside the
 * shared screen. This is the SDK's own message callback, not a transcript: only
 * the most recent agent turn is kept, and nothing is stored or sent anywhere. */
export type AgentUtterance = {
  text: string;
  at: string;
};

type SessionTokenResponse = {
  token: string;
  conversation_id: string;
};

type SessionSelection = {
  /** Which Process is being trained or learned. Required to start a session. */
  processId: string | null;
  processTitle: string | null;
  mode: SessionMode;
};

export function useElevenLabsSession({
  mode,
  processId,
  processTitle,
}: SessionSelection) {
  const { endSession, startSession } = useConversationControls();
  const { isMuted, setMuted } = useConversationInput();
  const { isListening, isSpeaking } = useConversationMode();
  const { status } = useConversationStatus();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [connectionStartedAt, setConnectionStartedAt] = useState<string | null>(null);
  const [agentUtterance, setAgentUtterance] = useState<AgentUtterance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preparation, setPreparation] = useState<PreparationState>("idle");
  // The role this session actually started with, latched at the moment the user
  // started it. The workspace derives the intended mode from the visible tab, so
  // without this latch a tab switch mid-session would retroactively change
  // whether the session is an expert one, and with it whether observations are
  // persisted as evidence.
  const [activeMode, setActiveMode] = useState<SessionMode | null>(null);
  const attemptRef = useRef(0);
  const tokenRequestRef = useRef<AbortController | null>(null);

  const isPreparing = preparation !== "idle";
  const isSessionActive = isPreparing || status === "connecting" || status === "connected";

  const endVoiceSession = useCallback(() => {
    attemptRef.current += 1;
    tokenRequestRef.current?.abort();
    tokenRequestRef.current = null;
    endSession();
    setConversationId(null);
    setConnectionStartedAt(null);
    setAgentUtterance(null);
    setError(null);
    setPreparation("idle");
    setActiveMode(null);
  }, [endSession]);

  const startVoiceSession = useCallback(async () => {
    if (isSessionActive) return;

    // The tutor must never guess which Process is active, and a training session
    // with no Process would produce knowledge nothing could later teach.
    if (!processId) {
      setError("Choose a process before starting a session.");
      return;
    }

    const attempt = attemptRef.current + 1;
    attemptRef.current = attempt;
    setError(null);
    setConversationId(null);
    setConnectionStartedAt(null);
    setAgentUtterance(null);
    setPreparation("microphone");
    setActiveMode(mode);

    try {
      await requestMicrophonePermission();
    } catch (permissionError) {
      if (attemptRef.current !== attempt) return;
      setPreparation("idle");
      setActiveMode(null);
      setError(microphoneErrorMessage(permissionError));
      return;
    }

    if (attemptRef.current !== attempt) return;
    setPreparation("token");
    const controller = new AbortController();
    tokenRequestRef.current = controller;

    let sessionToken: SessionTokenResponse;
    try {
      sessionToken = await requestSessionToken(controller.signal);
    } catch (tokenError) {
      if (attemptRef.current !== attempt || isAbortError(tokenError)) return;
      setPreparation("idle");
      setActiveMode(null);
      setError("Could not start a secure voice session. Please try again.");
      return;
    } finally {
      if (tokenRequestRef.current === controller) tokenRequestRef.current = null;
    }

    if (attemptRef.current !== attempt) return;
    setConversationId(sessionToken.conversation_id);
    setPreparation("idle");

    try {
      startSession({
        conversationToken: sessionToken.token,
        // These dynamic variables drive deterministic workflow routing, fill the
        // tutor tool's process_id path parameter, and come back on the post-call
        // webhook so ingestion knows which Process was trained.
        dynamicVariables: {
          session_mode: mode,
          process_id: processId,
          greeting: buildGreeting(mode, processTitle),
        },
        onConnect: ({ conversationId: connectedConversationId }) => {
          if (attemptRef.current !== attempt) return;
          setConversationId(connectedConversationId);
          setConnectionStartedAt(new Date().toISOString());
          setError(null);
        },
        // Only the newest agent turn is retained, so the UI can show what
        // Metadosis just asked without accumulating a transcript in the browser.
        onMessage: ({ message, role }) => {
          if (attemptRef.current !== attempt || role !== "agent") return;
          const spoken = message.trim();
          if (spoken) setAgentUtterance({ text: spoken, at: new Date().toISOString() });
        },
        onDisconnect: (details) => {
          if (attemptRef.current !== attempt) return;
          setConversationId(null);
          setConnectionStartedAt(null);
          setAgentUtterance(null);
          setActiveMode(null);
          if (details.reason === "error") {
            setError("The voice session disconnected unexpectedly. Please try again.");
          }
        },
        onError: () => {
          if (attemptRef.current !== attempt) return;
          setConversationId(null);
          setConnectionStartedAt(null);
          setAgentUtterance(null);
          setActiveMode(null);
          setError("Could not connect to the AI Apprentice. Please try again.");
        },
      });
    } catch {
      setConversationId(null);
      setConnectionStartedAt(null);
      setAgentUtterance(null);
      setActiveMode(null);
      setError("Could not connect to the AI Apprentice. Please try again.");
    }
  }, [isSessionActive, mode, processId, processTitle, startSession]);

  useEffect(() => {
    return () => {
      attemptRef.current += 1;
      tokenRequestRef.current?.abort();
      endSession();
    };
  }, [endSession]);

  return {
    activeMode,
    agentUtterance,
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
  };
}

// The agent's first message is a fixed string rather than a generated turn, so
// the learner hears something the moment the call connects instead of waiting on
// the model (and, in teaching mode, on the knowledge lookup). It is built here
// because only the browser knows both the mode and the chosen process name.
//
// In an expert session it also carries the one introductory question Metadosis
// asks: who the person is and what they are about to teach. It lives here, in
// the opening line, precisely so it cannot grow into an interview — the Capture
// node is told the intro is already done and never asks again. The answer is
// useful as transcript context for the distiller, which is why nothing about
// profession or years of experience is modelled in the Work Map schema.
export function buildGreeting(
  mode: SessionMode,
  processTitle: string | null,
): string {
  const subject = processTitle?.trim();

  if (mode === "teaching") {
    return subject
      ? `Hey, I'm Metadosis. Let's work through ${subject} together. Give me one second to pull up what the expert taught me.`
      : "Hey, I'm Metadosis. Give me one second to pull up what the expert taught me.";
  }

  const intro =
    "Hi, I'm Metadosis. I help preserve the knowledge people build up over years of work, so it can be passed on to someone else. " +
    "Quick intro first: what kind of work you do, roughly how long you've been doing it, and ";
  // The rhythm is part of the opening because the agent's question budget is
  // per task. If the expert does not know to work one task at a time, the
  // agent has no natural point at which to ask, and the session degrades into
  // the continuous interview this greeting exists to prevent.
  const rhythm =
    " please please work on one task at a time, I'll will ask some questions to make sure I understand what you're doing.";
  return subject
    ? `${intro}what you'll be showing me today about ${subject}.${rhythm}`
    : `${intro}what you're going to teach me today.${rhythm}`;
}

async function requestMicrophonePermission(): Promise<void> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone capture is unavailable");
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  for (const track of stream.getTracks()) track.stop();
}

async function requestSessionToken(signal: AbortSignal): Promise<SessionTokenResponse> {
  const response = await fetch("/api/elevenlabs/session", {
    method: "POST",
    cache: "no-store",
    signal,
  });
  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok || !isSessionTokenResponse(payload)) {
    throw new Error("Conversation token request failed");
  }
  return payload;
}

function isSessionTokenResponse(value: unknown): value is SessionTokenResponse {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<SessionTokenResponse>;
  return (
    typeof candidate.token === "string" &&
    candidate.token.length > 0 &&
    typeof candidate.conversation_id === "string" &&
    candidate.conversation_id.length > 0
  );
}

function microphoneErrorMessage(error: unknown): string {
  if (
    error instanceof DOMException &&
    (error.name === "NotAllowedError" || error.name === "SecurityError")
  ) {
    return "Microphone access is required for a voice session.";
  }
  return "A microphone is unavailable. Check your device and try again.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
