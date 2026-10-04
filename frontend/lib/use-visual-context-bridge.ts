"use client";

import { useConversationControls } from "@elevenlabs/react";
import { useEffect, useRef } from "react";

import type { SessionMode } from "@/lib/use-elevenlabs-session";
import type { VisualEvent } from "@/lib/visual-observation-api";

const VISUAL_CONTEXT_ID = "metadosis-current-visual-observation";
const MAX_VISUAL_HISTORY_EVENTS = 5;
const MAX_VISUAL_SUMMARY_LENGTH = 300;

type VisualContextBridge = {
  conversationId: string | null;
  isConnected: boolean;
  mode: SessionMode;
  screenActive: boolean;
  cameraActive: boolean;
  /** Screen and camera observations already merged into one ordered stream. */
  visualEvents: readonly VisualEvent[];
};

/**
 * Keeps the live agent aware of what the shared screen and camera are showing.
 *
 * Both modes receive visual context. The expert's observations give the
 * Apprentice something to ask about; the learner's let the Tutor compare what it
 * sees against the expert knowledge it loaded. What differs is persistence,
 * which the capture hook owns, not what the agent is told.
 *
 * Treat accepted observations as a queue, not as "the latest event". Screen and
 * camera requests complete independently, so a newly appended event can sort
 * behind an already-observed event. Events can also arrive while the voice
 * connection is still opening. Acknowledging every currently queued event only
 * after one self-contained snapshot is sent prevents both losses.
 */
export function useVisualContextBridge({
  conversationId,
  isConnected,
  mode,
  screenActive,
  cameraActive,
  visualEvents,
}: VisualContextBridge): void {
  const { sendContextualUpdate } = useConversationControls();
  const deliveredVisualEventIdsRef = useRef(new Set<string>());
  const deliveredVisualStateRef = useRef<string | null>(null);
  const bridgeConversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!isConnected || !conversationId) return;

    if (bridgeConversationIdRef.current !== conversationId) {
      bridgeConversationIdRef.current = conversationId;
      deliveredVisualEventIdsRef.current.clear();
      deliveredVisualStateRef.current = null;
    }

    const pendingEvents = visualEvents.filter(
      (event) => !deliveredVisualEventIdsRef.current.has(event.event_id),
    );
    const visualState = `${screenActive}:${cameraActive}`;
    const sourceStateChanged = deliveredVisualStateRef.current !== visualState;
    const hasActiveSource = screenActive || cameraActive;
    if (
      pendingEvents.length === 0 &&
      (!sourceStateChanged ||
        (!hasActiveSource && deliveredVisualStateRef.current === null))
    ) {
      return;
    }

    try {
      sendContextualUpdate(
        formatVisualContext(visualEvents, mode, screenActive, cameraActive),
        { contextId: VISUAL_CONTEXT_ID },
      );
      for (const event of pendingEvents) {
        deliveredVisualEventIdsRef.current.add(event.event_id);
      }
      deliveredVisualStateRef.current = visualState;
    } catch (sendError) {
      // Keep every pending ID unacknowledged so reconnecting or receiving the
      // next observation retries the complete current snapshot.
      console.error("Could not send visual context to ElevenLabs", sendError);
    }
  }, [
    cameraActive,
    conversationId,
    isConnected,
    mode,
    screenActive,
    sendContextualUpdate,
    visualEvents,
  ]);
}

function formatVisualContext(
  events: readonly VisualEvent[],
  mode: SessionMode,
  screenActive: boolean,
  cameraActive: boolean,
): string {
  const recent = events.slice(-MAX_VISUAL_HISTORY_EVENTS).map((event) => ({
    label: event.source === "camera" ? "[CAMERA]" : "[SCREEN]",
    summary: event.summary.trim().slice(0, MAX_VISUAL_SUMMARY_LENGTH),
  }));
  const current = recent.at(-1);
  const heading =
    mode === "learning"
      ? "VISUAL OBSERVATIONS (passive context from the expert's shared screen and camera, oldest to newest; not a user message):"
      : "VISUAL OBSERVATIONS (passive context from the learner's shared screen and camera, oldest to newest; not a user message):";

  const activeSources = [
    screenActive ? "screen" : null,
    cameraActive ? "camera" : null,
  ].filter(Boolean);

  return [
    heading,
    `ACTIVE INPUTS: ${activeSources.length > 0 ? activeSources.join(" and ") : "none"}.`,
    "An active input means its browser capture is connected. It does not imply a meaningful action has occurred yet.",
    "[SCREEN] describes their screen. [CAMERA] describes what they are physically doing.",
    ...(recent.length > 0
      ? [
          ...recent.map(
            (entry, index) => `${index + 1}. ${entry.label} ${entry.summary}`,
          ),
          `CURRENT: ${current?.label} ${current?.summary}`,
        ]
      : ["No meaningful visual change has been observed yet."]),
    "Treat this as a self-contained snapshot. Do not respond solely because of this update.",
  ].join("\n");
}
