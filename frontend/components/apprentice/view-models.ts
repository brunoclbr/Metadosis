import type { VisualCaptureStatus } from "@/lib/use-visual-capture";
import type { VisualEvent } from "@/lib/visual-observation-api";

/**
 * One visual input as the Teach and Learn surfaces need it.
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

/** Which side of the exchange the person in front of the browser is on. */
export type SessionKind = "teach" | "learn";

/** The live voice session, reduced to what the product surfaces actually show. */
export type SessionView = {
  /** True only once the apprentice is connected and can hear the person. */
  isLive: boolean;
  /** Microphone permission, token mint, or WebRTC handshake still in flight. */
  isStarting: boolean;
  /** Human-readable phase, e.g. "Requesting microphone". */
  statusLabel: string;
  /** `hh:mm:ss` since the connection opened, or null when not live. */
  clock: string | null;
  error: string | null;
  start: () => void;
  cancel: () => void;
};

export function isVisualSourceActive(status: VisualCaptureStatus): boolean {
  // "requesting" counts as active too: the stage must already be rendering its
  // <video> element (not the idle placeholder) when the browser's permission
  // prompt resolves, or startCapture finds videoRef.current still null.
  return (
    status === "requesting" || status === "capturing" || status === "processing"
  );
}

/**
 * Screen and camera observations as one ordered timeline.
 *
 * They describe the same moment of work — "they opened the ticket, then picked
 * up the wrench" — so both the agent and the UI reason about one stream rather
 * than two feeds.
 */
export function mergeVisualEvents(
  screenEvents: readonly VisualEvent[],
  cameraEvents: readonly VisualEvent[],
): VisualEvent[] {
  return [...screenEvents, ...cameraEvents].sort(
    (first, second) =>
      Date.parse(first.occurred_at) - Date.parse(second.occurred_at),
  );
}
