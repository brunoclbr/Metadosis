"use client";

import {
  CameraIcon,
  ClockIcon,
  PlusIcon,
  ScreenIcon,
  WaveformIcon,
} from "@/components/apprentice/icons";
import type { SessionKind } from "@/components/apprentice/view-models";

type SessionSidebarProps = {
  kind: SessionKind;
  subject: string | null;
  phase: "idle" | "starting" | "live";
  statusLabel: string;
  clock: string | null;
  isScreenOn: boolean;
  isCameraOn: boolean;
  isMuted: boolean;
  isSpeaking: boolean;
  isListening: boolean;
  /** Whether what Metadosis sees becomes durable evidence. True only for an
   * expert's session; a learner's observations coach them and are never kept. */
  persistsObservations: boolean;
  onToggleMute: () => void;
  onFinish: () => void;
  onNewSession: () => void;
};

export function SessionSidebar({
  clock,
  isCameraOn,
  isListening,
  isMuted,
  isScreenOn,
  isSpeaking,
  kind,
  onFinish,
  onNewSession,
  onToggleMute,
  persistsObservations,
  phase,
  statusLabel,
  subject,
}: SessionSidebarProps) {
  const isLive = phase === "live";
  const isWatching = isScreenOn || isCameraOn;

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          M
        </span>
        <span className="brand-name">Metadosis</span>
      </div>
      <p className="brand-tagline">Knowledge that outlives the expert.</p>

      <section className="session-card" aria-label="Session status">
        <span className="eyebrow">
          {kind === "teach" ? "Teaching session" : "Learning session"}
        </span>

        {phase === "idle" ? (
          <>
            <p className="session-idle">No active session</p>
            <button className="btn btn-block" type="button" onClick={onNewSession}>
              <PlusIcon />
              New session
            </button>
          </>
        ) : (
          <>
            <strong className="session-subject">{subject ?? "Untitled process"}</strong>

            {isLive ? (
              <>
                <ul className="signal-list">
                  <li>
                    <span className={dotClass(isWatching)} aria-hidden="true" />
                    {isWatching ? "Watching" : "Not watching"}
                  </li>
                  <li>
                    <span className={dotClass(!isMuted)} aria-hidden="true" />
                    {voiceLabel(isMuted, isSpeaking, isListening)}
                  </li>
                  <li className="signal-clock">
                    <ClockIcon />
                    <time>{clock ?? "00:00:00"}</time>
                  </li>
                </ul>

                <ul className="device-list">
                  <DeviceRow label="Screen" icon={<ScreenIcon />} isOn={isScreenOn} />
                  <DeviceRow label="Camera" icon={<CameraIcon />} isOn={isCameraOn} />
                  <DeviceRow label="Voice" icon={<WaveformIcon />} isOn={!isMuted} />
                </ul>

                <p className="session-privacy">
                  {persistsObservations
                    ? "Observations are saved with this session."
                    : "Nothing from this session is saved."}
                </p>

                <div className="session-actions">
                  <button className="btn btn-block" type="button" onClick={onToggleMute}>
                    {isMuted ? "Unmute" : "Mute"}
                  </button>
                  <button
                    className="btn btn-accent btn-block"
                    type="button"
                    onClick={onFinish}
                  >
                    {kind === "teach" ? "Finish teaching" : "End session"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="session-idle">{statusLabel}</p>
                <button className="btn btn-block" type="button" onClick={onFinish}>
                  Cancel
                </button>
              </>
            )}
          </>
        )}
      </section>

      <p className="sidebar-foot">Teach. Learn. Pass it on.</p>
    </aside>
  );
}

function DeviceRow({
  icon,
  isOn,
  label,
}: {
  icon: React.ReactNode;
  isOn: boolean;
  label: string;
}) {
  return (
    <li>
      {icon}
      <span>{label}</span>
      <span className={dotClass(isOn)} aria-hidden="true" />
      <span className="sr-only">{isOn ? "on" : "off"}</span>
    </li>
  );
}

function dotClass(isOn: boolean): string {
  return `dot${isOn ? " is-on" : ""}`;
}

function voiceLabel(
  isMuted: boolean,
  isSpeaking: boolean,
  isListening: boolean,
): string {
  if (isMuted) return "Muted";
  if (isSpeaking) return "Speaking";
  if (isListening) return "Listening";
  return "Connected";
}
