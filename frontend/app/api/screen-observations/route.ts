import { NextResponse } from "next/server";

const CANONICAL_BRAIN_BACKEND_URL =
  "https://backend-production-8255.up.railway.app";
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
const MAX_PAIR_BYTES = 2 * MAX_IMAGE_BYTES;
const REQUEST_TIMEOUT_MS = 65_000;
const PAIR_CONTENT_TYPE = "application/octet-stream";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request): Promise<Response> {
  const contentType = (request.headers.get("content-type") ?? "")
    .split(";", 1)[0]
    .trim();
  if (contentType !== PAIR_CONTENT_TYPE) {
    return errorResponse("Invalid visual comparison content type.", 415);
  }

  const metadata = readComparisonHeaders(request.headers);
  if (!metadata) {
    return errorResponse("Visual comparison metadata is invalid.", 400);
  }

  const expectedBytes =
    Number(metadata["X-Screen-Previous-Bytes"]) +
    Number(metadata["X-Screen-Current-Bytes"]);
  const declaredBytes = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredBytes) && declaredBytes > MAX_PAIR_BYTES) {
    return errorResponse("The visual frame pair is too large.", 413);
  }
  if (declaredBytes > 0 && declaredBytes !== expectedBytes) {
    return errorResponse("Visual frame byte lengths do not match.", 400);
  }

  const boundedBody = await readBoundedBody(request);
  if (boundedBody.kind === "too-large") {
    return errorResponse("The visual frame pair is too large.", 413);
  }
  if (boundedBody.kind === "empty" || boundedBody.body.byteLength !== expectedBytes) {
    return errorResponse("Visual frame byte lengths do not match.", 400);
  }

  try {
    const backendResponse = await fetch(getBackendVisualObservationUrl(), {
      method: "POST",
      headers: {
        "Content-Type": PAIR_CONTENT_TYPE,
        ...metadata,
      },
      body: boundedBody.body,
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (backendResponse.status === 204) {
      return new Response(null, {
        status: 204,
        headers: { "Cache-Control": "no-store" },
      });
    }
    if (!backendResponse.ok) {
      console.error("FastAPI visual event comparison failed", {
        status: backendResponse.status,
        sessionId: metadata["X-Screen-Session-Id"],
        previousFrameId: metadata["X-Screen-Previous-Frame-Id"],
        currentFrameId: metadata["X-Screen-Current-Frame-Id"],
      });
      return errorResponse(messageForStatus(backendResponse.status), backendResponse.status);
    }

    const payload: unknown = await backendResponse.json().catch(() => null);
    if (!payload) {
      return errorResponse("The vision backend returned an invalid response.", 502);
    }
    return NextResponse.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse("The vision model took too long to respond.", 504);
    }
    console.error("Could not reach the FastAPI visual event endpoint", {
      sessionId: metadata["X-Screen-Session-Id"],
      previousFrameId: metadata["X-Screen-Previous-Frame-Id"],
      currentFrameId: metadata["X-Screen-Current-Frame-Id"],
    });
    return errorResponse("The vision backend is unavailable.", 502);
  }
}

export async function PUT(request: Request): Promise<Response> {
  const payload: unknown = await request.json().catch(() => null);
  if (!isPersistedVisualEvent(payload)) {
    return errorResponse("Visual event correlation is invalid.", 400);
  }

  try {
    const backendResponse = await fetch(getBackendVisualEventUrl(), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    const responsePayload: unknown = await backendResponse.json().catch(() => null);
    if (!backendResponse.ok) {
      console.error("FastAPI visual event persistence failed", {
        status: backendResponse.status,
        eventId: payload.event_id,
      });
      return errorResponse(
        backendResponse.status === 409
          ? "The visual event is already assigned to another conversation."
          : "The visual event could not be saved.",
        backendResponse.status,
      );
    }
    return NextResponse.json(responsePayload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse("Saving the visual event took too long.", 504);
    }
    console.error("Could not reach the FastAPI visual event persistence endpoint", {
      eventId: payload.event_id,
    });
    return errorResponse("The visual event could not be saved.", 502);
  }
}

async function readBoundedBody(
  request: Request,
): Promise<
  | { kind: "body"; body: ArrayBuffer }
  | { kind: "empty" }
  | { kind: "too-large" }
> {
  if (!request.body) return { kind: "empty" };

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let byteLength = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      byteLength += value.byteLength;
      if (byteLength > MAX_PAIR_BYTES) {
        await reader.cancel();
        return { kind: "too-large" };
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  if (byteLength === 0) return { kind: "empty" };

  const combined = new Uint8Array(byteLength);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { kind: "body", body: combined.buffer };
}

function getBackendVisualObservationUrl(): string {
  return getBackendUrl("/screen-observations");
}

function getBackendVisualEventUrl(): string {
  return getBackendUrl("/screen-observations/events");
}

function getBackendUrl(path: string): string {
  // Keep visual evidence beside the Process that ElevenLabs teaches from. A
  // local frontend otherwise writes frames to local Postgres while the agent's
  // tool and post-call webhook read and distill the deployed Brain.
  const configuredUrl =
    process.env.BRAIN_BACKEND_URL ??
    (process.env.NODE_ENV === "production"
      ? process.env.BACKEND_CHAT_URL
      : undefined);
  if (!configuredUrl && process.env.NODE_ENV === "production") {
    throw new Error("BRAIN_BACKEND_URL or BACKEND_CHAT_URL is required in production.");
  }
  return new URL(path, configuredUrl ?? CANONICAL_BRAIN_BACKEND_URL).toString();
}

function readComparisonHeaders(headers: Headers): Record<string, string> | null {
  const sessionId = headers.get("x-screen-session-id") ?? "";
  const previousFrameId = headers.get("x-screen-previous-frame-id") ?? "";
  const currentFrameId = headers.get("x-screen-current-frame-id") ?? "";
  const occurredAt = headers.get("x-screen-occurred-at") ?? "";
  const changeScore = headers.get("x-screen-change-score") ?? "";
  const previousWidth = headers.get("x-screen-previous-width") ?? "";
  const previousHeight = headers.get("x-screen-previous-height") ?? "";
  const currentWidth = headers.get("x-screen-current-width") ?? "";
  const currentHeight = headers.get("x-screen-current-height") ?? "";
  const previousBytes = headers.get("x-screen-previous-bytes") ?? "";
  const currentBytes = headers.get("x-screen-current-bytes") ?? "";
  const imageType = headers.get("x-screen-image-type") ?? "";
  // Absent means screen: a browser build that predates camera capture described
  // exactly one input, and the backend applies the same default.
  const visualSource = headers.get("x-visual-source") ?? "screen";
  const threadId = headers.get("x-thread-id");

  if (
    !UUID_PATTERN.test(sessionId) ||
    !isPositiveInteger(previousFrameId) ||
    !isPositiveInteger(currentFrameId) ||
    Number(previousFrameId) >= Number(currentFrameId) ||
    Number.isNaN(Date.parse(occurredAt)) ||
    !isNormalizedScore(changeScore) ||
    !isDimension(previousWidth) ||
    !isDimension(previousHeight) ||
    !isDimension(currentWidth) ||
    !isDimension(currentHeight) ||
    !isImageByteLength(previousBytes) ||
    !isImageByteLength(currentBytes) ||
    imageType !== "image/jpeg" ||
    !isVisualSource(visualSource) ||
    (threadId !== null && (threadId.length === 0 || threadId.length > 256))
  ) {
    return null;
  }

  const result: Record<string, string> = {
    "X-Screen-Session-Id": sessionId,
    "X-Screen-Previous-Frame-Id": previousFrameId,
    "X-Screen-Current-Frame-Id": currentFrameId,
    "X-Screen-Occurred-At": occurredAt,
    "X-Screen-Change-Score": changeScore,
    "X-Screen-Previous-Width": previousWidth,
    "X-Screen-Previous-Height": previousHeight,
    "X-Screen-Current-Width": currentWidth,
    "X-Screen-Current-Height": currentHeight,
    "X-Screen-Previous-Bytes": previousBytes,
    "X-Screen-Current-Bytes": currentBytes,
    "X-Screen-Image-Type": imageType,
    "X-Visual-Source": visualSource,
  };
  if (threadId) result["X-Thread-Id"] = threadId;
  return result;
}

function isPersistedVisualEvent(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object") return false;
  const event = value as Record<string, unknown>;
  return (
    typeof event.conversation_id === "string" &&
    event.conversation_id.length > 0 &&
    event.conversation_id.length <= 256 &&
    typeof event.event_id === "string" &&
    UUID_PATTERN.test(event.event_id) &&
    typeof event.session_id === "string" &&
    UUID_PATTERN.test(event.session_id) &&
    typeof event.previous_frame_id === "number" &&
    Number.isSafeInteger(event.previous_frame_id) &&
    event.previous_frame_id > 0 &&
    typeof event.current_frame_id === "number" &&
    Number.isSafeInteger(event.current_frame_id) &&
    event.current_frame_id > event.previous_frame_id &&
    typeof event.occurred_at === "string" &&
    !Number.isNaN(Date.parse(event.occurred_at)) &&
    typeof event.change_score === "number" &&
    event.change_score >= 0 &&
    event.change_score <= 1 &&
    typeof event.summary === "string" &&
    event.summary.length > 0 &&
    event.summary.length <= 4_000 &&
    (event.time_in_call_secs === undefined ||
      (typeof event.time_in_call_secs === "number" &&
        Number.isFinite(event.time_in_call_secs) &&
        event.time_in_call_secs >= 0)) &&
    (event.source === "screen" || event.source === "camera")
  );
}

function isVisualSource(value: string): boolean {
  return value === "screen" || value === "camera";
}

function isPositiveInteger(value: string): boolean {
  return /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0;
}

function isDimension(value: string): boolean {
  return isPositiveInteger(value) && Number(value) <= 8192;
}

function isImageByteLength(value: string): boolean {
  return isPositiveInteger(value) && Number(value) <= MAX_IMAGE_BYTES;
}

function isNormalizedScore(value: string): boolean {
  const parsed = Number(value);
  return value.length > 0 && Number.isFinite(parsed) && parsed >= 0 && parsed <= 1;
}

function messageForStatus(status: number): string {
  if (status === 413) return "The visual frame pair is too large.";
  if (status === 415) return "The visual frame pair type is unsupported.";
  if (status === 504) return "The vision model took too long to respond.";
  if (status === 400 || status === 422) return "The visual frame pair was invalid.";
  return "The vision model could not compare the frames.";
}

function errorResponse(error: string, status: number): NextResponse<{ error: string }> {
  return NextResponse.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
