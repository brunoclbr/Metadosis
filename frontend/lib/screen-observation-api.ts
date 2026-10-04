export type ScreenFrame = {
  blob: Blob;
  frameId: number;
  capturedAt: string;
  width: number;
  height: number;
};

export type ScreenEvent = {
  event_id: string;
  session_id: string;
  previous_frame_id: number;
  current_frame_id: number;
  occurred_at: string;
  change_score: number;
  summary: string;
};

type ScreenComparison = {
  previous: ScreenFrame;
  current: ScreenFrame;
  sessionId: string;
  changeScore: number;
  threadId?: string;
};

export async function compareScreenFrames(
  comparison: ScreenComparison,
  signal?: AbortSignal,
): Promise<ScreenEvent | null> {
  const { previous, current } = comparison;
  const headers: Record<string, string> = {
    "Content-Type": "application/octet-stream",
    "X-Screen-Image-Type": "image/jpeg",
    "X-Screen-Session-Id": comparison.sessionId,
    "X-Screen-Previous-Frame-Id": String(previous.frameId),
    "X-Screen-Current-Frame-Id": String(current.frameId),
    "X-Screen-Occurred-At": current.capturedAt,
    "X-Screen-Change-Score": comparison.changeScore.toFixed(6),
    "X-Screen-Previous-Width": String(previous.width),
    "X-Screen-Previous-Height": String(previous.height),
    "X-Screen-Current-Width": String(current.width),
    "X-Screen-Current-Height": String(current.height),
    "X-Screen-Previous-Bytes": String(previous.blob.size),
    "X-Screen-Current-Bytes": String(current.blob.size),
  };
  if (comparison.threadId) headers["X-Thread-Id"] = comparison.threadId;

  const response = await fetch("/api/screen-observations", {
    method: "POST",
    headers,
    body: new Blob([previous.blob, current.blob]),
    cache: "no-store",
    signal,
  });
  if (response.status === 204) return null;

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(
      isErrorResponse(payload)
        ? payload.error
        : "The screen change could not be processed.",
    );
  }
  if (!isScreenEvent(payload)) {
    throw new Error("The screen event response was invalid.");
  }
  return payload;
}

export async function persistScreenEvent(
  conversationId: string,
  event: ScreenEvent,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/screen-observations", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId, ...event }),
    cache: "no-store",
    signal,
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(
      isErrorResponse(payload)
        ? payload.error
        : "The screen observation could not be saved.",
    );
  }
}

function isScreenEvent(value: unknown): value is ScreenEvent {
  if (!isRecord(value)) return false;
  return (
    typeof value.event_id === "string" &&
    typeof value.session_id === "string" &&
    typeof value.previous_frame_id === "number" &&
    typeof value.current_frame_id === "number" &&
    typeof value.occurred_at === "string" &&
    typeof value.change_score === "number" &&
    value.change_score >= 0 &&
    value.change_score <= 1 &&
    typeof value.summary === "string"
  );
}

function isErrorResponse(value: unknown): value is { error: string } {
  return isRecord(value) && typeof value.error === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
