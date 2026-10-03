import { NextResponse } from "next/server";

import {
  isChatRequest,
  isChatResponse,
  type ErrorResponse,
} from "@/lib/chat-contract";

const DEFAULT_BACKEND_CHAT_URL = "http://127.0.0.1:8000/chat";
const REQUEST_TIMEOUT_MS = 120_000;

function getBackendChatUrl(): string {
  const configuredUrl = process.env.BACKEND_CHAT_URL;

  if (configuredUrl) {
    return configuredUrl;
  }

  if (process.env.NODE_ENV === "production") {
    throw new Error("BACKEND_CHAT_URL is required in production.");
  }

  return DEFAULT_BACKEND_CHAT_URL;
}

export async function POST(request: Request): Promise<Response> {
  const payload: unknown = await request.json().catch(() => null);

  if (!isChatRequest(payload)) {
    return errorResponse("A message and thread ID are required.", 400);
  }

  try {
    // Keep the backend address server-side. Besides avoiding browser CORS setup,
    // this prevents clients from turning a configurable proxy into an SSRF surface.
    const backendResponse = await fetch(
      getBackendChatUrl(),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        cache: "no-store",
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      },
    );

    if (!backendResponse.ok) {
      // Record transport metadata without copying provider or backend details into logs.
      console.error("FastAPI chat request failed", {
        status: backendResponse.status,
      });
      return errorResponse("The agent backend rejected the request.", 502);
    }

    const contentType = backendResponse.headers.get("content-type") ?? "";
    if (contentType.startsWith("audio/") && backendResponse.body) {
      // Preserve the upstream ReadableStream. Converting it to a Blob here would
      // buffer the complete response and undo FastAPI's chunked speech delivery.
      return new Response(backendResponse.body, {
        headers: {
          "Cache-Control": "no-store",
          "Content-Type": contentType,
        },
      });
    }

    const backendPayload: unknown = await backendResponse.json().catch(() => null);
    if (!isChatResponse(backendPayload)) {
      console.error("FastAPI returned an invalid chat response shape");
      return errorResponse("The agent backend returned an invalid response.", 502);
    }

    return NextResponse.json(backendPayload);
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse("The agent took too long to respond.", 504);
    }

    console.error("Could not reach the FastAPI chat backend", error);
    return errorResponse("The agent backend is unavailable.", 502);
  }
}

function errorResponse(error: string, status: number): NextResponse<ErrorResponse> {
  return NextResponse.json({ error }, { status });
}
