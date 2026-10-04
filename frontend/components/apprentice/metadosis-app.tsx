"use client";

import { ConversationProvider } from "@elevenlabs/react";
import { useCallback, useMemo, useState } from "react";

import { LearnPanel } from "@/components/apprentice/learn-panel";
import { ModeNav, type WorkspaceMode } from "@/components/apprentice/mode-nav";
import { SessionSidebar } from "@/components/apprentice/session-sidebar";
import { TeachPanel } from "@/components/apprentice/teach-panel";
import {
  isVisualSourceActive,
  mergeVisualEvents,
  type SessionKind,
  type SessionView,
  type VisualSourceView,
} from "@/components/apprentice/view-models";
import { VisualStage } from "@/components/apprentice/visual-stage";
import {
  type SessionMode,
  useElevenLabsSession,
} from "@/lib/use-elevenlabs-session";
import { useProcesses } from "@/lib/use-processes";
import { useSessionClock } from "@/lib/use-session-clock";
import {
  type VisualCaptureController,
  useVisualCapture,
} from "@/lib/use-visual-capture";
import { useVisualContextBridge } from "@/lib/use-visual-context-bridge";

/**
 * The whole product: a sidebar that reports the live session, three modes, and
 * one shared view of what Metadosis can see.
 *
 * The conversation provider wraps everything because the session is not owned by
 * any single mode — the sidebar reports it, Teach and Learn each start it, and
 * the shared view reacts to it.
 */
export function MetadosisApp({ initialSessionId }: { initialSessionId: string }) {
  return (
    <ConversationProvider>
      <Workspace initialSessionId={initialSessionId} />
    </ConversationProvider>
  );
}

function Workspace({ initialSessionId }: { initialSessionId: string }) {
  const [threadId, setThreadId] = useState(initialSessionId);
  const [mode, setMode] = useState<WorkspaceMode>("teach");
  const [selectedProcessId, setSelectedProcessId] = useState<string | null>(null);
  // Backend contract, not product language: "learning" means Metadosis is
  // learning from an expert, "teaching" means it is tutoring a newcomer. One
  // selection drives the whole session, and the mode that made it decides which
  // ElevenLabs branch runs.
  const [sessionMode, setSessionMode] = useState<SessionMode>("learning");
  const [finishNotice, setFinishNotice] = useState<string | null>(null);

  const {
    addProcess,
    error: processError,
    isCreating,
    isLoading: areProcessesLoading,
    processes,
  } = useProcesses();
  const selectedProcess =
    processes.find((item) => item.id === selectedProcessId) ?? null;
  const isExpertSession = sessionMode === "learning";

  const {
    agentUtterance,
    connectionStartedAt,
    conversationId,
    endVoiceSession,
    error: sessionError,
    isListening,
    isMuted,
    isSessionActive,
    isSpeaking,
    preparation,
    setMuted,
    startVoiceSession,
    status,
  } = useElevenLabsSession({
    mode: sessionMode,
    processId: selectedProcessId,
    processTitle: selectedProcess?.title ?? null,
  });
  const isConnected = status === "connected";

  // Screen and camera are independent captures of the same session. Only an
  // expert session persists what they see: a learner's observations coach them
  // live and must never be stored as though an expert had demonstrated them.
  const screenCapture = useVisualCapture({
    source: "screen",
    threadId,
    conversationId: isConnected ? conversationId : null,
    connectionStartedAt: isConnected ? connectionStartedAt : null,
    persist: isExpertSession,
  });
  const cameraCapture = useVisualCapture({
    source: "camera",
    threadId,
    conversationId: isConnected ? conversationId : null,
    connectionStartedAt: isConnected ? connectionStartedAt : null,
    persist: isExpertSession,
  });
  const isScreenOn = isVisualSourceActive(screenCapture.status);
  const isCameraOn = isVisualSourceActive(cameraCapture.status);

  const visualEvents = useMemo(
    () => mergeVisualEvents(screenCapture.events, cameraCapture.events),
    [cameraCapture.events, screenCapture.events],
  );
  useVisualContextBridge({
    conversationId,
    isConnected,
    mode: sessionMode,
    screenActive: isScreenOn,
    cameraActive: isCameraOn,
    visualEvents,
  });

  const clock = useSessionClock(isConnected ? connectionStartedAt : null);
  const screenView = toSourceView(screenCapture);
  const cameraView = toSourceView(cameraCapture);

  const stopCapture = screenCapture.stopCapture;
  const stopCamera = cameraCapture.stopCapture;

  // Finishing stops the media tracks as well as the call, so the expert does not
  // leave a screen share running after the apprentice has stopped listening.
  const finishSession = useCallback(() => {
    // Only Teach shows the notice, so only Teach may set one; otherwise ending a
    // Learn session would leave a message waiting in a tab it never described.
    const shouldConfirm = isConnected && isExpertSession;
    endVoiceSession();
    stopCapture();
    stopCamera();
    setFinishNotice(
      shouldConfirm
        ? "Teaching session finished. Screen and camera sharing were stopped — if your browser still shows a sharing bar, close it there."
        : null,
    );
  }, [endVoiceSession, isConnected, isExpertSession, stopCamera, stopCapture]);

  const startNewSession = useCallback(() => {
    endVoiceSession();
    stopCapture();
    stopCamera();
    setThreadId(`web-${crypto.randomUUID()}`);
    setSelectedProcessId(null);
    setFinishNotice(null);
  }, [endVoiceSession, stopCamera, stopCapture]);

  const selectForTeaching = useCallback((processId: string) => {
    setSelectedProcessId(processId);
    setSessionMode("learning");
  }, []);

  const selectForLearning = useCallback((processId: string) => {
    setSelectedProcessId(processId);
    setSessionMode("teaching");
  }, []);

  const createForTeaching = useCallback(
    async (title: string) => {
      const created = await addProcess(title);
      if (created) selectForTeaching(created.id);
    },
    [addProcess, selectForTeaching],
  );

  // A selection belongs to the mode that made it, so switching tabs cannot start
  // a session against a process that was chosen for the opposite purpose.
  const teachProcess = isExpertSession ? selectedProcess : null;
  const learnProcess = isExpertSession ? null : selectedProcess;
  const statusLabel = sessionStatusLabel(preparation, status);
  const sessionKind: SessionKind = isSessionActive
    ? isExpertSession
      ? "teach"
      : "learn"
    : mode === "learn"
      ? "learn"
      : "teach";

  const session = (kind: SessionKind): SessionView => ({
    isLive: isConnected && sessionKind === kind,
    isStarting: isSessionActive && !isConnected && sessionKind === kind,
    statusLabel,
    clock,
    error: sessionError,
    start: () => void startVoiceSession(),
    cancel: endVoiceSession,
  });

  return (
    <div className="app-shell">
      <SessionSidebar
        kind={sessionKind}
        subject={selectedProcess?.title ?? null}
        phase={isConnected ? "live" : isSessionActive ? "starting" : "idle"}
        statusLabel={statusLabel}
        clock={clock}
        isScreenOn={isScreenOn}
        isCameraOn={isCameraOn}
        isMuted={isMuted}
        isSpeaking={isSpeaking}
        isListening={isListening}
        persistsObservations={isExpertSession}
        onToggleMute={() => setMuted(!isMuted)}
        onFinish={finishSession}
        onNewSession={startNewSession}
      />

      <div className="workspace">
        <ModeNav mode={mode} onChange={setMode} />

        <div className="workspace-body">
          <TeachPanel
            hidden={mode !== "teach"}
            processes={processes}
            selectedProcess={teachProcess}
            isLoadingProcesses={areProcessesLoading}
            isCreatingProcess={isCreating}
            processError={processError}
            onSelectProcess={selectForTeaching}
            onCreateProcess={createForTeaching}
            screen={screenView}
            camera={cameraView}
            session={session("teach")}
            finishNotice={finishNotice}
            onDismissNotice={() => setFinishNotice(null)}
          />

          <LearnPanel
            hidden={mode !== "learn"}
            processes={processes}
            selectedProcess={learnProcess}
            isLoadingProcesses={areProcessesLoading}
            processError={processError}
            onSelectProcess={selectForLearning}
            onClearProcess={() => setSelectedProcessId(null)}
            screen={screenView}
            camera={cameraView}
            session={session("learn")}
          />

          <section
            id="brain-panel"
            className="mode-panel placeholder-mode"
            role="tabpanel"
            aria-labelledby="brain-tab"
            hidden={mode !== "brain"}
          >
            <span className="eyebrow">Metadosis</span>
            <h1>Brain</h1>
            <p>Coming next</p>
          </section>

          {/* Mounted once and never unmounted while a capture runs: two copies
              would fight over one hook's video ref. */}
          <VisualStage
            screen={screenView}
            screenVideoRef={screenCapture.videoRef}
            camera={cameraView}
            cameraVideoRef={cameraCapture.videoRef}
            offstage={mode === "brain"}
            idleBehavior={mode === "learn" && learnProcess ? "placeholder" : "hide"}
            isLive={isConnected}
            isSpeaking={isSpeaking}
            agentUtterance={agentUtterance}
          />
        </div>
      </div>
    </div>
  );
}

function toSourceView(controller: VisualCaptureController): VisualSourceView {
  return {
    events: controller.events,
    error: controller.error,
    status: controller.status,
    start: () => void controller.startCapture(),
    stop: controller.stopCapture,
  };
}

function sessionStatusLabel(
  preparation: "idle" | "microphone" | "token",
  status: "disconnected" | "connecting" | "connected" | "error",
): string {
  if (preparation === "microphone") return "Requesting microphone…";
  if (preparation === "token") return "Securing session…";
  if (status === "connecting") return "Connecting…";
  if (status === "connected") return "Connected";
  if (status === "error") return "Connection error";
  return "Disconnected";
}
