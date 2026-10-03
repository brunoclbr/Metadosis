"use client";

import Link from "next/link";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

import { VoiceSessionControls } from "@/components/apprentice/voice-session-controls";
import { useChat } from "@/lib/use-chat";
import { useScreenShare } from "@/lib/use-screen-share";

type ChatShellProps = {
  initialThreadId: string;
};

export function ChatShell({ initialThreadId }: ChatShellProps) {
  const {
    error,
    isPending,
    messages,
    sendMessage,
    startNewChat,
    threadId,
  } = useChat(initialThreadId);
  const {
    error: screenShareError,
    events: screenEvents,
    startSharing,
    status: screenShareStatus,
    stopSharing,
    videoRef,
  } = useScreenShare(threadId);
  const isScreenSharing =
    screenShareStatus === "sharing" || screenShareStatus === "processing";
  const [draft, setDraft] = useState("");
  const endOfMessages = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endOfMessages.current?.scrollIntoView({ behavior: "smooth" });
  }, [isPending, messages]);

  function submitMessage(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isPending) {
      return;
    }

    setDraft("");
    void sendMessage(message);
  }

  function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div>
          <Link className="brand" href="/" aria-label="Agent Chat home">
            <span className="brand-mark" aria-hidden="true">
              A
            </span>
            <span>Agent Chat</span>
          </Link>
          <p className="sidebar-copy">
            A focused interface for your LangGraph agent.
          </p>
        </div>

        <div className="conversation-panel">
          <span className="eyebrow">Current conversation</span>
          <code className="thread-id" title={threadId}>
            {threadId}
          </code>
          <button className="new-chat-button" type="button" onClick={startNewChat}>
            <PlusIcon />
            New chat
          </button>
        </div>

        <VoiceSessionControls screenEvents={screenEvents} />

        <section className="screen-share-panel" aria-label="Screen sharing">
          <div className="screen-share-heading">
            <span className="eyebrow">Visual context</span>
            <span className={`screen-share-state state-${screenShareStatus}`}>
              {screenShareStatus}
            </span>
          </div>
          <video
            className={`screen-preview${isScreenSharing ? " is-active" : ""}`}
            ref={videoRef}
            muted
            playsInline
            aria-label="Shared screen preview"
          />
          {isScreenSharing ? (
            <button
              className="screen-share-button stop"
              type="button"
              onClick={stopSharing}
            >
              Stop sharing
            </button>
          ) : (
            <button
              className="screen-share-button"
              type="button"
              onClick={() => void startSharing()}
              disabled={screenShareStatus === "requesting"}
            >
              {screenShareStatus === "requesting" ? "Requesting…" : "Start sharing"}
            </button>
          )}
          {screenShareError && (
            <p className="screen-share-error" role="alert">
              {screenShareError}
            </p>
          )}
          {screenEvents.length > 0 && (
            <div className="screen-events" aria-live="polite">
              <span>Screen events</span>
              <ol>
                {screenEvents.map((screenEvent) => (
                  <li key={screenEvent.event_id}>
                    <time dateTime={screenEvent.occurred_at}>
                      {formatEventTime(screenEvent.occurred_at)}
                    </time>
                    <p>{screenEvent.summary}</p>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>

        <p className="sidebar-note">
          Shared frames are processed transiently and are not saved.
        </p>
      </aside>

      <section className="chat-panel" aria-label="Agent conversation">
        <header className="chat-header">
          <div>
            <span className="eyebrow">Workspace</span>
            <h1>How can I help?</h1>
          </div>
          <div className="status-pill" aria-live="polite">
            <span className="status-dot" aria-hidden="true" />
            {isPending ? "Agent working" : "Ready"}
          </div>
        </header>

        <div className="message-list" aria-live="polite">
          {messages.length === 0 ? (
            <EmptyConversation />
          ) : (
            <div className="messages">
              {messages.map((message) => (
                <article
                  className={`message message-${message.role}`}
                  key={message.id}
                >
                  <span className="message-role">
                    {message.role === "user" ? "You" : "Agent"}
                  </span>
                  {message.audioUrl ? (
                    <AudioReply audioUrl={message.audioUrl} />
                  ) : (
                    <div className="message-content">
                      <Markdown>{message.content}</Markdown>
                    </div>
                  )}
                </article>
              ))}
              {isPending && <ThinkingMessage />}
            </div>
          )}
          <div ref={endOfMessages} />
        </div>

        <div className="composer-area">
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
          <form className="composer" onSubmit={submitMessage}>
            <label className="sr-only" htmlFor="chat-message">
              Message the agent
            </label>
            <textarea
              id="chat-message"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={submitOnEnter}
              placeholder="Message the agent"
              rows={1}
              disabled={isPending}
            />
            <button
              className="send-button"
              type="submit"
              disabled={isPending || draft.trim().length === 0}
              aria-label="Send message"
            >
              <ArrowIcon />
            </button>
          </form>
          <p className="composer-hint">Enter to send · Shift + Enter for a new line</p>
        </div>
      </section>
    </main>
  );
}

function formatEventTime(occurredAt: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(occurredAt));
}

function EmptyConversation() {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true">
        <SparkIcon />
      </div>
      <h2>Start a conversation</h2>
      <p>
        Ask a question, share context, or give the agent a task. This conversation
        will continue under the thread shown in the sidebar.
      </p>
    </div>
  );
}

function AudioReply({ audioUrl }: { audioUrl: string }) {
  return (
    <div className="audio-reply">
      {/* Native controls keep this blueprint accessible and make autoplay failure
          harmless: the user can always start the streamed response manually. */}
      <audio controls autoPlay preload="auto" src={audioUrl}>
        Your browser does not support streamed audio playback.
      </audio>
    </div>
  );
}

function ThinkingMessage() {
  return (
    <article className="message message-assistant thinking-message">
      <span className="message-role">Agent</span>
      <span className="thinking-dots" aria-label="Agent is thinking">
        <i />
        <i />
        <i />
      </span>
    </article>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m5 12 7-7 7 7M12 5v14" />
    </svg>
  );
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <path d="M16 3c.8 7.6 5.4 12.2 13 13-7.6.8-12.2 5.4-13 13-.8-7.6-5.4-12.2-13-13C10.6 15.2 15.2 10.6 16 3Z" />
    </svg>
  );
}
