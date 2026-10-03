import { NextResponse } from "next/server";

const DEFAULT_BACKEND_CHAT_URL = "http://127.0.0.1:8000/chat";
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 65_000;
const ALLOWED_CONTENT_TYPES = new Set(["image/jpeg"]);
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request): Promise<Response> {
  const contentType = (request.headers.get("content-type") ?? "")
    .split(";", 1)[0]
    .trim();
  if (!ALLOWED_CONTENT_TYPES.has(contentType)) {
    return errorResponse("Only JPEG screen frames are supported.", 415);
  }

  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_IMAGE_BYTES) {
    return errorResponse("The screen frame is too large.", 413);
  }

  const correlationHeaders = readCorrelationHeaders(request.headers);
  if (!correlationHeaders) {
    return errorResponse("Screen frame metadata is invalid.", 400);
  }

  const boundedBody = await readBoundedBody(request);
  if (boundedBody.kind === "empty") {
    return errorResponse("A screen frame is required.", 400);
  }
  if (boundedBody.kind === "too-large") {
    return errorResponse("The screen frame is too large.", 413);
  }

  try {
    const backendResponse = await fetch(getBackendScreenObservationUrl(), {
      method: "POST",
      headers: {
        "Content-Type": contentType,
        ...correlationHeaders,
      },
      body: boundedBody.body,
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (!backendResponse.ok) {
      console.error("FastAPI screen observation request failed", {
        status: backendResponse.status,
        sessionId: correlationHeaders["X-Screen-Session-Id"],
        frameId: correlationHeaders["X-Screen-Frame-Id"],
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
    console.error("Could not reach the FastAPI screen observation endpoint", {
      sessionId: correlationHeaders["X-Screen-Session-Id"],
      frameId: correlationHeaders["X-Screen-Frame-Id"],
    });
    return errorResponse("The vision backend is unavailable.", 502);
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
      if (byteLength > MAX_IMAGE_BYTES) {
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

function getBackendScreenObservationUrl(): string {
  const configuredUrl = process.env.BACKEND_CHAT_URL;
  if (!configuredUrl && process.env.NODE_ENV === "production") {
    throw new Error("BACKEND_CHAT_URL is required in production.");
  }
  return new URL(
    "/screen-observations",
    configuredUrl ?? DEFAULT_BACKEND_CHAT_URL,
  ).toString();
}

function readCorrelationHeaders(headers: Headers): Record<string, string> | null {
  const sessionId = headers.get("x-screen-session-id") ?? "";
  const frameId = headers.get("x-screen-frame-id") ?? "";
  const capturedAt = headers.get("x-screen-captured-at") ?? "";
  const width = headers.get("x-screen-width") ?? "";
  const height = headers.get("x-screen-height") ?? "";
  const threadId = headers.get("x-thread-id");

  if (
    !UUID_PATTERN.test(sessionId) ||
    !isPositiveInteger(frameId) ||
    Number.isNaN(Date.parse(capturedAt)) ||
    !isPositiveInteger(width) ||
    !isPositiveInteger(height) ||
    Number(width) > 8192 ||
    Number(height) > 8192 ||
    (threadId !== null && (threadId.length === 0 || threadId.length > 256))
  ) {
    return null;
  }

  const result: Record<string, string> = {
    "X-Screen-Session-Id": sessionId,
    "X-Screen-Frame-Id": frameId,
    "X-Screen-Captured-At": capturedAt,
    "X-Screen-Width": width,
    "X-Screen-Height": height,
  };
  if (threadId) result["X-Thread-Id"] = threadId;
  return result;
}

function isPositiveInteger(value: string): boolean {
  return /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0;
}

function messageForStatus(status: number): string {
  if (status === 413) return "The screen frame is too large.";
  if (status === 415) return "The screen frame type is unsupported.";
  if (status === 504) return "The vision model took too long to respond.";
  if (status === 400 || status === 422) return "The screen frame was invalid.";
  return "The vision model could not process the screen frame.";
}

function errorResponse(error: string, status: number): NextResponse<{ error: string }> {
  return NextResponse.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
