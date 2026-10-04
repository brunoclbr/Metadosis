"use client";

import Link from "next/link";
import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Markdown from "react-markdown";

import { VisualInputPanel } from "@/components/apprentice/visual-input-panel";
import { VoiceSessionControls } from "@/components/apprentice/voice-session-controls";
import type { Process } from "@/lib/process-api";
import { useChat } from "@/lib/use-chat";
import { useProcesses } from "@/lib/use-processes";
import {
  type VisualCaptureStatus,
  useVisualCapture,
} from "@/lib/use-visual-capture";

type ChatShellProps = {
  initialThreadId: string;
};

type WorkspaceTab = "teach" | "learn" | "brain";

const WORKSPACE_TABS: ReadonlyArray<{ id: WorkspaceTab; label: string }> = [
  { id: "teach", label: "Teach Metadosis" },
  { id: "learn", label: "Learn" },
  { id: "brain", label: "Brain" },
];

export function ChatShell({ initialThreadId }: ChatShellProps) {
  const {
    error,
    isPending,
    messages,
    sendMessage,
    startNewChat,
    threadId,
  } = useChat(initialThreadId);
  const [voiceConversationId, setVoiceConversationId] = useState<string | null>(null);
  const [voiceConnectionStartedAt, setVoiceConnectionStartedAt] = useState<
    string | null
  >(null);
  const handleVoiceConversationChange = useCallback(
    (conversationId: string | null, connectionStartedAt: string | null) => {
      setVoiceConversationId(conversationId);
      setVoiceConnectionStartedAt(connectionStartedAt);
    },
    [],
  );
  const {
    addProcess,
    error: processError,
    isCreating,
    isLoading: areProcessesLoading,
    processes,
  } = useProcesses();
  // One selection drives the whole session. Which tab made it decides whether
  // ElevenLabs routes to the capture branch or the tutor branch.
  const [selectedProcessId, setSelectedProcessId] = useState<string | null>(null);
  const [sessionMode, setSessionMode] = useState<"learning" | "teaching">("learning");
  // Screen and camera are independent captures of the same session. Only an
  // expert session persists what they see: a learner's observations coach them
  // live and must never be stored as though an expert had demonstrated them.
  const isExpertSession = sessionMode === "learning";
  const screenCapture = useVisualCapture({
    source: "screen",
    threadId,
    conversationId: voiceConversationId,
    connectionStartedAt: voiceConnectionStartedAt,
    persist: isExpertSession,
  });
  const cameraCapture = useVisualCapture({
    source: "camera",
    threadId,
    conversationId: voiceConversationId,
    connectionStartedAt: voiceConnectionStartedAt,
    persist: isExpertSession,
  });
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("teach");
  const selectedProcess =
    processes.find((item) => item.id === selectedProcessId) ?? null;
  const [draft, setDraft] = useState("");
  const messageListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const messageList = messageListRef.current;
    messageList?.scrollTo({ top: messageList.scrollHeight, behavior: "smooth" });
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

        <VoiceSessionControls
          screenEvents={screenCapture.events}
          cameraEvents={cameraCapture.events}
          screenActive={isVisualCaptureActive(screenCapture.status)}
          cameraActive={isVisualCaptureActive(cameraCapture.status)}
          onConversationChange={handleVoiceConversationChange}
          processId={selectedProcessId}
          processTitle={selectedProcess?.title ?? null}
          mode={sessionMode}
        />

        <p className="sidebar-note">
          {isExpertSession
            ? "Shared frames are processed transiently; meaningful observations are saved with the voice session."
            : "Shared frames are processed transiently and used only to coach you during this session. Nothing is saved."}
        </p>
      </aside>

      <section className="workspace-shell">
        <nav className="workspace-tabs" aria-label="Metadosis modes" role="tablist">
          {WORKSPACE_TABS.map((tab) => (
            <button
              id={`${tab.id}-tab`}
              className={activeTab === tab.id ? "is-active" : ""}
              key={tab.id}
              type="button"
              role="tab"
              aria-controls={`${tab.id}-panel`}
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {activeTab !== "brain" && (
          <VisualInputPanel
            screen={{
              events: screenCapture.events,
              error: screenCapture.error,
              status: screenCapture.status,
              start: () => void screenCapture.startCapture(),
              stop: screenCapture.stopCapture,
            }}
            screenVideoRef={screenCapture.videoRef}
            camera={{
              events: cameraCapture.events,
              error: cameraCapture.error,
              status: cameraCapture.status,
              start: () => void cameraCapture.startCapture(),
              stop: cameraCapture.stopCapture,
            }}
            cameraVideoRef={cameraCapture.videoRef}
            mode={sessionMode}
          />
        )}

        <div
          id="teach-panel"
          className="workspace-mode teach-workspace"
          role="tabpanel"
          aria-labelledby="teach-tab"
          hidden={activeTab !== "teach"}
        >
          <ProcessPicker
            processes={processes}
            selectedProcessId={selectedProcessId}
            isLoading={areProcessesLoading}
            isCreating={isCreating}
            error={processError}
            onSelect={(processId) => {
              setSelectedProcessId(processId);
              setSessionMode("learning");
            }}
            onCreate={async (title, description) => {
              const created = await addProcess(title, description);
              if (created) {
                setSelectedProcessId(created.id);
                setSessionMode("learning");
              }
            }}
          />

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

        <div className="message-list" aria-live="polite" ref={messageListRef}>
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
        </div>

        <section
          id="learn-panel"
          className="workspace-mode learn-workspace"
          role="tabpanel"
          aria-labelledby="learn-tab"
          hidden={activeTab !== "learn"}
        >
          <span className="eyebrow">Metadosis workspace</span>
          <h1>What do you want to learn?</h1>
          {areProcessesLoading ? (
            <p>Loading processes…</p>
          ) : processes.length === 0 ? (
            <p>
              Nothing has been taught yet. Train a process in Teach Metadosis
              first.
            </p>
          ) : (
            <ul className="process-list">
              {processes.map((process) => (
                <li key={process.id}>
                  <button
                    className={`process-option${
                      selectedProcessId === process.id && sessionMode === "teaching"
                        ? " is-selected"
                        : ""
                    }`}
                    type="button"
                    aria-pressed={
                      selectedProcessId === process.id && sessionMode === "teaching"
                    }
                    onClick={() => {
                      setSelectedProcessId(process.id);
                      setSessionMode("teaching");
                    }}
                  >
                    <strong>{process.title}</strong>
                    {process.description && <span>{process.description}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {processError && (
            <p className="screen-share-error" role="alert">
              {processError}
            </p>
          )}
          {selectedProcess && sessionMode === "teaching" && (
            <p className="process-hint">
              Start the voice session in the sidebar to be tutored on{" "}
              <strong>{selectedProcess.title}</strong>.
            </p>
          )}
        </section>
        <PlaceholderMode
          id="brain-panel"
          labelledBy="brain-tab"
          title="Brain"
          hidden={activeTab !== "brain"}
        />
      </section>
    </main>
  );
}

function ProcessPicker({
  error,
  isCreating,
  isLoading,
  onCreate,
  onSelect,
  processes,
  selectedProcessId,
}: {
  error: string | null;
  isCreating: boolean;
  isLoading: boolean;
  onCreate: (title: string, description?: string) => Promise<void>;
  onSelect: (processId: string) => void;
  processes: readonly Process[];
  selectedProcessId: string | null;
}) {
  const [isNaming, setIsNaming] = useState(false);
  const [title, setTitle] = useState("");

  async function submitNewProcess(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed || isCreating) return;

    await onCreate(trimmed);
    setTitle("");
    setIsNaming(false);
  }

  return (
    <section className="process-panel" aria-label="Process to train">
      <div className="process-panel-heading">
        <span className="eyebrow">Process</span>
        <h2>What are you teaching Metadosis?</h2>
      </div>

      {isLoading ? (
        <p>Loading processes…</p>
      ) : (
        <div className="process-controls">
          <label className="sr-only" htmlFor="process-select">
            Choose a process
          </label>
          <select
            id="process-select"
            value={selectedProcessId ?? ""}
            onChange={(event) => {
              if (event.target.value) onSelect(event.target.value);
            }}
          >
            <option value="" disabled>
              {processes.length === 0 ? "No processes yet" : "Choose a process"}
            </option>
            {processes.map((process) => (
              <option value={process.id} key={process.id}>
                {process.title}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => setIsNaming((current) => !current)}>
            {isNaming ? "Cancel" : "+ New process"}
          </button>
        </div>
      )}

      {isNaming && (
        <form className="process-form" onSubmit={submitNewProcess}>
          <label className="sr-only" htmlFor="process-title">
            New process name
          </label>
          <input
            id="process-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="e.g. Supplier invoice processing"
            maxLength={200}
            autoFocus
          />
          <button type="submit" disabled={isCreating || title.trim().length === 0}>
            {isCreating ? "Creating…" : "Create"}
          </button>
        </form>
      )}

      {error && (
        <p className="screen-share-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function PlaceholderMode({
  hidden,
  id,
  labelledBy,
  title,
}: {
  hidden: boolean;
  id: string;
  labelledBy: string;
  title: string;
}) {
  return (
    <section
      id={id}
      className="workspace-mode placeholder-mode"
      role="tabpanel"
      aria-labelledby={labelledBy}
      hidden={hidden}
    >
      <span className="eyebrow">Metadosis workspace</span>
      <h1>{title}</h1>
      <p>Coming next</p>
    </section>
  );
}

function isVisualCaptureActive(status: VisualCaptureStatus): boolean {
  return status === "capturing" || status === "processing";
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
