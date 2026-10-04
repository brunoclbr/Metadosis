import { NextResponse } from "next/server";

const CANONICAL_BRAIN_BACKEND_URL =
  "https://backend-production-8255.up.railway.app";
const REQUEST_TIMEOUT_MS = 15_000;

export async function GET(
  _request: Request,
  context: RouteContext<"/api/brain/processes/[processId]/graph">,
): Promise<Response> {
  const { processId } = await context.params;

  try {
    const backendResponse = await fetch(
      getBackendUrl(`/brain/processes/${encodeURIComponent(processId)}/graph`),
      {
        cache: "no-store",
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      },
    );
    const payload: unknown = await backendResponse.json().catch(() => null);

    if (backendResponse.status === 404) {
      return NextResponse.json(
        { error: "Nothing captured here yet." },
        { status: 404, headers: { "Cache-Control": "no-store" } },
      );
    }
    if (!backendResponse.ok || !payload) {
      console.error("FastAPI Brain graph request failed", {
        status: backendResponse.status,
      });
      return errorResponse("The Brain couldn't be loaded.", 502);
    }
    return NextResponse.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse("Opening the Brain took too long.", 504);
    }
    console.error("Could not reach the FastAPI Brain graph endpoint");
    return errorResponse("The Brain couldn't be loaded.", 502);
  }
}

function getBackendUrl(path: string): string {
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

function errorResponse(error: string, status: number): NextResponse<{ error: string }> {
  return NextResponse.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
