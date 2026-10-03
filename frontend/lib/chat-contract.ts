export type ChatRequest = {
  message: string;
  thread_id: string;
};

export type ChatResponse = {
  response: string;
};

export type ErrorResponse = {
  error: string;
};

export function isChatRequest(value: unknown): value is ChatRequest {
  if (!isRecord(value)) {
    return false;
  }

  return (
    typeof value.message === "string" &&
    value.message.trim().length > 0 &&
    typeof value.thread_id === "string" &&
    value.thread_id.trim().length > 0
  );
}

export function isChatResponse(value: unknown): value is ChatResponse {
  return isRecord(value) && typeof value.response === "string";
}

export function isErrorResponse(value: unknown): value is ErrorResponse {
  return isRecord(value) && typeof value.error === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
