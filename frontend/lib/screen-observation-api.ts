export type ScreenFrame = {
  blob: Blob;
  sessionId: string;
  frameId: number;
  capturedAt: string;
  width: number;
  height: number;
  threadId?: string;
};

export type ScreenObservation = {
  observation_id: string;
  session_id: string;
  frame_id: number;
  captured_at: string;
  description: string;
  model: {
    provider: string;
    name: string;
  };
};

export async function sendScreenFrame(
  frame: ScreenFrame,
  signal?: AbortSignal,
): Promise<ScreenObservation> {
  const headers: Record<string, string> = {
    "Content-Type": frame.blob.type,
    "X-Screen-Session-Id": frame.sessionId,
    "X-Screen-Frame-Id": String(frame.frameId),
    "X-Screen-Captured-At": frame.capturedAt,
    "X-Screen-Width": String(frame.width),
    "X-Screen-Height": String(frame.height),
  };
  if (frame.threadId) headers["X-Thread-Id"] = frame.threadId;

  const response = await fetch("/api/screen-observations", {
    method: "POST",
    headers,
    body: frame.blob,
    cache: "no-store",
    signal,
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(
      isErrorResponse(payload)
        ? payload.error
        : "The screen observation could not be processed.",
    );
  }
  if (!isScreenObservation(payload)) {
    throw new Error("The screen observation response was invalid.");
  }
  return payload;
}

function isScreenObservation(value: unknown): value is ScreenObservation {
  if (!isRecord(value) || !isRecord(value.model)) return false;
  return (
    typeof value.observation_id === "string" &&
    typeof value.session_id === "string" &&
    typeof value.frame_id === "number" &&
    typeof value.captured_at === "string" &&
    typeof value.description === "string" &&
    typeof value.model.provider === "string" &&
    typeof value.model.name === "string"
  );
}

function isErrorResponse(value: unknown): value is { error: string } {
  return isRecord(value) && typeof value.error === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
