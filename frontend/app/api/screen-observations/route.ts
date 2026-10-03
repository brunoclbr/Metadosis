import { NextResponse } from "next/server";

const DEFAULT_BACKEND_CHAT_URL = "http://127.0.0.1:8000/chat";
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
    return errorResponse("Invalid screen comparison content type.", 415);
  }

  const metadata = readComparisonHeaders(request.headers);
  if (!metadata) {
    return errorResponse("Screen comparison metadata is invalid.", 400);
  }

  const expectedBytes =
    Number(metadata["X-Screen-Previous-Bytes"]) +
    Number(metadata["X-Screen-Current-Bytes"]);
  const declaredBytes = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredBytes) && declaredBytes > MAX_PAIR_BYTES) {
    return errorResponse("The screen frame pair is too large.", 413);
  }
  if (declaredBytes > 0 && declaredBytes !== expectedBytes) {
    return errorResponse("Screen frame byte lengths do not match.", 400);
  }

  const boundedBody = await readBoundedBody(request);
  if (boundedBody.kind === "too-large") {
    return errorResponse("The screen frame pair is too large.", 413);
  }
  if (boundedBody.kind === "empty" || boundedBody.body.byteLength !== expectedBytes) {
    return errorResponse("Screen frame byte lengths do not match.", 400);
  }

  try {
    const backendResponse = await fetch(getBackendScreenObservationUrl(), {
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
      console.error("FastAPI screen event comparison failed", {
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
    console.error("Could not reach the FastAPI screen event endpoint", {
      sessionId: metadata["X-Screen-Session-Id"],
      previousFrameId: metadata["X-Screen-Previous-Frame-Id"],
      currentFrameId: metadata["X-Screen-Current-Frame-Id"],
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
  };
  if (threadId) result["X-Thread-Id"] = threadId;
  return result;
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
  if (status === 413) return "The screen frame pair is too large.";
  if (status === 415) return "The screen frame pair type is unsupported.";
  if (status === 504) return "The vision model took too long to respond.";
  if (status === 400 || status === 422) return "The screen frame pair was invalid.";
  return "The vision model could not compare the screen frames.";
}

function errorResponse(error: string, status: number): NextResponse<{ error: string }> {
  return NextResponse.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
