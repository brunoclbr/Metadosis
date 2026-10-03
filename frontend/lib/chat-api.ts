import {
  isChatResponse,
  isErrorResponse,
  type ChatRequest,
} from "@/lib/chat-contract";

export type ChatResult =
  | { kind: "text"; response: string }
  | { kind: "audio"; audioUrl: string };

export async function sendChatMessage(
  request: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatResult> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const message = isErrorResponse(payload)
      ? payload.error
      : "The agent could not complete the request.";
    throw new Error(message);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.startsWith("audio/") && response.body) {
    return {
      kind: "audio",
      audioUrl: createStreamingAudioUrl(response.body, contentType.split(";")[0]),
    };
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!isChatResponse(payload)) {
    throw new Error("The agent returned an unexpected response.");
  }

  return { kind: "text", response: payload.response };
}

function createStreamingAudioUrl(
  stream: ReadableStream<Uint8Array>,
  contentType: string,
): string {
  if (!MediaSource.isTypeSupported(contentType)) {
    throw new Error(`Streaming ${contentType} audio is not supported by this browser.`);
  }

  // MediaSource gives the <audio> element a stable URL immediately. Chunks arriving
  // from FastAPI are appended below, so playback can begin before synthesis ends.
  const mediaSource = new MediaSource();
  const audioUrl = URL.createObjectURL(mediaSource);
  mediaSource.addEventListener(
    "sourceopen",
    () => void pipeAudio(stream, mediaSource, contentType),
    { once: true },
  );
  return audioUrl;
}

async function pipeAudio(
  stream: ReadableStream<Uint8Array>,
  mediaSource: MediaSource,
  contentType: string,
): Promise<void> {
  const sourceBuffer = mediaSource.addSourceBuffer(contentType);
  const reader = stream.getReader();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // SourceBuffer accepts one append at a time. Waiting for updateend preserves
      // provider chunk order and avoids calling appendBuffer while it is updating.
      await appendChunk(sourceBuffer, new Uint8Array(value).buffer);
    }
    if (mediaSource.readyState === "open") mediaSource.endOfStream();
  } catch (error) {
    console.error("Audio stream failed", error);
    if (mediaSource.readyState === "open") mediaSource.endOfStream("network");
  } finally {
    reader.releaseLock();
  }
}

function appendChunk(sourceBuffer: SourceBuffer, chunk: ArrayBuffer): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      sourceBuffer.removeEventListener("updateend", onUpdateEnd);
      sourceBuffer.removeEventListener("error", onError);
    };
    const onUpdateEnd = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error("The browser could not buffer the audio stream."));
    };

    sourceBuffer.addEventListener("updateend", onUpdateEnd, { once: true });
    sourceBuffer.addEventListener("error", onError, { once: true });
    sourceBuffer.appendBuffer(chunk);
  });
}
