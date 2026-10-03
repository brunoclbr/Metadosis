import { NextResponse } from "next/server";

const ELEVENLABS_TOKEN_URL =
  "https://api.elevenlabs.io/v1/convai/conversation/token";
const REQUEST_TIMEOUT_MS = 10_000;

type ConversationToken = {
  token: string;
  conversation_id: string;
};

export async function POST(): Promise<Response> {
  const apiKey = process.env.ELEVENLABS_API_KEY?.trim();
  const agentId = process.env.ELEVENLABS_AGENT_ID?.trim();

  if (!apiKey || !agentId) {
    console.error("ElevenLabs session configuration is incomplete");
    return errorResponse("Voice sessions are not configured.", 503);
  }

  const url = new URL(ELEVENLABS_TOKEN_URL);
  url.searchParams.set("agent_id", agentId);

  try {
    const upstreamResponse = await fetch(url, {
      headers: { "xi-api-key": apiKey },
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (!upstreamResponse.ok) {
      const errorPayload: unknown = await upstreamResponse.json().catch(() => null);
      console.error("ElevenLabs conversation token request failed", {
        status: upstreamResponse.status,
        providerStatus: providerErrorStatus(errorPayload),
        requiredPermission: providerRequiredPermission(errorPayload),
      });
      return errorResponse("Could not start a secure voice session.", 502);
    }

    const payload: unknown = await upstreamResponse.json().catch(() => null);
    if (!isConversationToken(payload)) {
      console.error("ElevenLabs returned an invalid conversation token response");
      return errorResponse("Could not start a secure voice session.", 502);
    }

    return NextResponse.json(
      {
        token: payload.token,
        conversation_id: payload.conversation_id,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    if (error instanceof Error && error.name === "TimeoutError") {
      return errorResponse("The voice service took too long to respond.", 504);
    }

    console.error("Could not reach the ElevenLabs conversation token endpoint");
    return errorResponse("The voice service is unavailable.", 502);
  }
}

function isConversationToken(value: unknown): value is ConversationToken {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<ConversationToken>;
  return (
    typeof candidate.token === "string" &&
    candidate.token.length > 0 &&
    typeof candidate.conversation_id === "string" &&
    candidate.conversation_id.length > 0
  );
}

function providerErrorStatus(value: unknown): string {
  if (!value || typeof value !== "object") return "unknown";

  const detail = (value as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return "unknown";

  const status = (detail as { status?: unknown }).status;
  if (typeof status !== "string" || !/^[a-z0-9_-]{1,64}$/i.test(status)) {
    return "unknown";
  }
  return status;
}

function providerRequiredPermission(value: unknown): string {
  if (!value || typeof value !== "object") return "unknown";

  const detail = (value as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return "unknown";

  const message = (detail as { message?: unknown }).message;
  if (typeof message !== "string") return "unknown";

  const knownPermissions = [
    "convai_read",
    "convai_write",
    "agents_read",
    "agents_write",
    "conversations_read",
    "conversations_write",
  ] as const;
  return knownPermissions.find((permission) => message.includes(permission)) ?? "unknown";
}

function errorResponse(error: string, status: number): NextResponse<{ error: string }> {
  return NextResponse.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
