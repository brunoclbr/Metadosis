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

export function useElevenLabsSession() {
  const { endSession, startSession } = useConversationControls();
  const { isMuted, setMuted } = useConversationInput();
  const { isListening, isSpeaking } = useConversationMode();
  const { status } = useConversationStatus();
  const [selectedMode, setSelectedModeState] = useState<SessionMode>("learning");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preparation, setPreparation] = useState<PreparationState>("idle");
  const attemptRef = useRef(0);
  const tokenRequestRef = useRef<AbortController | null>(null);

  const isPreparing = preparation !== "idle";
  const isSessionActive = isPreparing || status === "connecting" || status === "connected";

  const setSelectedMode = useCallback(
    (mode: SessionMode) => {
      if (!isSessionActive) setSelectedModeState(mode);
    },
    [isSessionActive],
  );

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
        dynamicVariables: { session_mode: selectedMode },
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
  }, [isSessionActive, selectedMode, startSession]);

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
    selectedMode,
    setMuted,
    setSelectedMode,
    startVoiceSession,
    status,
  };
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
