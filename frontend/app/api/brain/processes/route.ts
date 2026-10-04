import { NextResponse } from "next/server";

const DEFAULT_BACKEND_CHAT_URL = "http://127.0.0.1:8000/chat";
const REQUEST_TIMEOUT_MS = 15_000;
const MAX_TITLE_LENGTH = 200;
const MAX_DESCRIPTION_LENGTH = 2_000;

type ProcessCreateRequest = {
  title: string;
  description?: string | null;
};

export async function GET(): Promise<Response> {
  try {
    const backendResponse = await fetch(getBackendUrl("/brain/processes"), {
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (!backendResponse.ok) {
      console.error("FastAPI process listing failed", {
        status: backendResponse.status,
      });
      return errorResponse("Processes could not be loaded.", 502);
    }

    const payload: unknown = await backendResponse.json().catch(() => null);
    if (!Array.isArray(payload)) {
      return errorResponse("The brain backend returned an invalid response.", 502);
    }
    return NextResponse.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse("Loading processes took too long.", 504);
    }
    console.error("Could not reach the FastAPI process endpoint");
    return errorResponse("The brain backend is unavailable.", 502);
  }
}

export async function POST(request: Request): Promise<Response> {
  const payload: unknown = await request.json().catch(() => null);
  if (!isProcessCreateRequest(payload)) {
    return errorResponse("A process title is required.", 400);
  }

  try {
    const backendResponse = await fetch(getBackendUrl("/brain/processes"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    const responsePayload: unknown = await backendResponse.json().catch(() => null);
    if (!backendResponse.ok) {
      console.error("FastAPI process creation failed", {
        status: backendResponse.status,
      });
      return errorResponse(
        backendResponse.status === 422
          ? "That process title is not valid."
          : "The process could not be created.",
        backendResponse.status === 422 ? 422 : 502,
      );
    }
    return NextResponse.json(responsePayload, {
      status: 201,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse("Creating the process took too long.", 504);
    }
    console.error("Could not reach the FastAPI process endpoint");
    return errorResponse("The process could not be created.", 502);
  }
}

// Keep the backend address server-side so a configurable proxy cannot be turned
// into an SSRF surface, matching the chat and screen-observation routes.
function getBackendUrl(path: string): string {
  const configuredUrl = process.env.BACKEND_CHAT_URL;
  if (!configuredUrl && process.env.NODE_ENV === "production") {
    throw new Error("BACKEND_CHAT_URL is required in production.");
  }
  return new URL(path, configuredUrl ?? DEFAULT_BACKEND_CHAT_URL).toString();
}

function isProcessCreateRequest(value: unknown): value is ProcessCreateRequest {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<ProcessCreateRequest>;
  if (
    typeof candidate.title !== "string" ||
    candidate.title.trim().length === 0 ||
    candidate.title.length > MAX_TITLE_LENGTH
  ) {
    return false;
  }
  if (
    candidate.description !== undefined &&
    candidate.description !== null &&
    (typeof candidate.description !== "string" ||
      candidate.description.length > MAX_DESCRIPTION_LENGTH)
  ) {
    return false;
  }
  return true;
}

function errorResponse(error: string, status: number): NextResponse<{ error: string }> {
  return NextResponse.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
