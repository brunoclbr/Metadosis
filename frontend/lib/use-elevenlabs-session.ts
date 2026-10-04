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
  const [error, setError] = useState<string | null>(null);
  const [preparation, setPreparation] = useState<PreparationState>("idle");
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
    setError(null);
    setPreparation("idle");
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
    setPreparation("microphone");

    try {
      await requestMicrophonePermission();
    } catch (permissionError) {
      if (attemptRef.current !== attempt) return;
      setPreparation("idle");
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
          setError(null);
        },
        onDisconnect: (details) => {
          if (attemptRef.current !== attempt) return;
          setConversationId(null);
          if (details.reason === "error") {
            setError("The voice session disconnected unexpectedly. Please try again.");
          }
        },
        onError: () => {
          if (attemptRef.current !== attempt) return;
          setConversationId(null);
          setError("Could not connect to the AI Apprentice. Please try again.");
        },
      });
    } catch {
      setConversationId(null);
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

  return subject
    ? `Hey, I'm Metadosis. Walk me through ${subject} the way you normally would, and I'll jump in when I need to understand why you did something.`
    : "Hey, I'm Metadosis. Just start with whatever you want me to learn, the way you'd normally do it, and I'll jump in when I need to understand why.";
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
