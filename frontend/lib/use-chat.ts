"use client";

import { useEffect, useRef, useState } from "react";

import { sendChatMessage } from "@/lib/chat-api";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  audioUrl?: string;
};

export function useChat(initialThreadId: string) {
  const [threadId, setThreadId] = useState(initialThreadId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const audioUrls = useRef<string[]>([]);

  useEffect(
    () => () => {
      activeRequest.current?.abort();
      audioUrls.current.forEach((url) => URL.revokeObjectURL(url));
    },
    [],
  );

  async function sendMessage(content: string): Promise<void> {
    const message = content.trim();
    if (!message || isPending || activeRequest.current) {
      return;
    }

    const controller = new AbortController();
    activeRequest.current = controller;
    setError(null);
    setIsPending(true);
    setMessages((current) => [
      ...current,
      createMessage("user", message),
    ]);

    try {
      const response = await sendChatMessage(
        { message, thread_id: threadId },
        controller.signal,
      );
      if (response.kind === "audio") audioUrls.current.push(response.audioUrl);
      setMessages((current) => [
        ...current,
        response.kind === "audio"
          ? createMessage("assistant", "", response.audioUrl)
          : createMessage("assistant", response.response),
      ]);
    } catch (requestError) {
      if (!controller.signal.aborted) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "The agent could not complete the request.",
        );
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setIsPending(false);
      }
    }
  }

  function startNewChat(): void {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setThreadId(createThreadId());
    audioUrls.current.forEach((url) => URL.revokeObjectURL(url));
    audioUrls.current = [];
    setMessages([]);
    setError(null);
    setIsPending(false);
  }

  return {
    error,
    isPending,
    messages,
    sendMessage,
    startNewChat,
    threadId,
  };
}

function createMessage(
  role: ChatMessage["role"],
  content: string,
  audioUrl?: string,
): ChatMessage {
  return { id: crypto.randomUUID(), role, content, audioUrl };
}

function createThreadId(): string {
  return `web-${crypto.randomUUID()}`;
}
