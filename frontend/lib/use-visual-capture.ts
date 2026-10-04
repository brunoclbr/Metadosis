"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  compareVisualFrames,
  persistVisualEvent,
  type VisualEvent,
  type VisualFrame,
  type VisualSource,
} from "@/lib/visual-observation-api";

export type VisualCaptureStatus =
  | "idle"
  | "requesting"
  | "capturing"
  | "processing"
  | "stopped"
  | "error";

const MAX_FRAME_DIMENSION = 1_280;
const JPEG_QUALITY = 0.76;
const MAX_FRAME_BYTES = 2 * 1024 * 1024;
const FINGERPRINT_WIDTH = 192;
const FINGERPRINT_HEIGHT = 108;
const BLOCK_WIDTH = 8;
const BLOCK_HEIGHT = 6;
const MAX_RECENT_EVENTS = 20;

type CaptureProfile = {
  /** How often a frame is examined in the browser. */
  sampleIntervalMs: number;
  /** Minimum wall-clock gap between two comparisons sent to the VLM. */
  cooldownMs: number;
  /** Whole-frame difference below which nothing is sent. */
  globalThreshold: number;
  /** Most-changed local block difference below which nothing is sent. */
  blockThreshold: number;
  /**
   * What the coarse comparison measures against: the immediately preceding
   * sample, or the last frame actually sent for analysis.
   */
  baseline: "previous-sample" | "last-sent";
};

// Screen and camera demand opposite instincts. A screen is static until someone
// acts, so a sensitive threshold on consecutive samples catches a recoloured
// sticky note. A camera never stops changing — a person breathes, the lens
// refocuses, the light shifts — so the same settings would fire constantly and
// say nothing. Camera capture therefore samples slowly, measures against the
// frame it last sent (so a scene that returns to a previous state is not
// re-reported), demands a far larger difference, and keeps a cooldown that caps
// VLM calls regardless of how much motion there is. The pixel test only decides
// what is worth looking at; the vision model still decides what is meaningful.
const CAPTURE_PROFILES: Record<VisualSource, CaptureProfile> = {
  screen: {
    sampleIntervalMs: 500,
    cooldownMs: 0,
    globalThreshold: 0.006,
    blockThreshold: 0.06,
    baseline: "previous-sample",
  },
  camera: {
    sampleIntervalMs: 4_000,
    cooldownMs: 6_000,
    globalThreshold: 0.035,
    blockThreshold: 0.2,
    baseline: "last-sent",
  },
};

type CapturedFrame = VisualFrame & {
  fingerprint: Uint8ClampedArray;
};

type VisualCaptureOptions = {
  source: VisualSource;
  threadId?: string;
  conversationId?: string | null;
  /** Browser timestamp from ElevenLabs onConnect; used only for approximate
   * call-relative alignment while the original capture UTC is preserved. */
  connectionStartedAt?: string | null;
  /**
   * Whether confirmed observations become durable evidence. True only while an
   * expert trains the Brain. A learner's observations exist to coach them in the
   * moment and are deliberately never written, so they cannot later be mistaken
   * for captured expertise.
   */
  persist: boolean;
};

export function useVisualCapture({
  source,
  threadId,
  conversationId,
  connectionStartedAt,
  persist,
}: VisualCaptureOptions) {
  const profile = CAPTURE_PROFILES[source];
  const [status, setStatus] = useState<VisualCaptureStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<VisualEvent[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const trackRef = useRef<MediaStreamTrack | null>(null);
  const trackEndedHandlerRef = useRef<(() => void) | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const requestInFlightRef = useRef(false);
  const sessionIdRef = useRef<string | null>(null);
  const frameIdRef = useRef(0);
  const threadIdRef = useRef(threadId);
  const conversationIdRef = useRef(conversationId);
  const connectionStartedAtRef = useRef(connectionStartedAt);
  const persistRef = useRef(persist);
  const eventConversationIdsRef = useRef(new Map<string, string>());
  const eventConnectionStartedAtsRef = useRef(new Map<string, string>());
  const persistedEventIdsRef = useRef(new Set<string>());
  const persistenceInFlightRef = useRef(new Set<string>());
  const previousFingerprintRef = useRef<Uint8ClampedArray | null>(null);
  const acceptedFrameRef = useRef<VisualFrame | null>(null);
  const acceptedFingerprintRef = useRef<Uint8ClampedArray | null>(null);
  const lastSentAtRef = useRef(0);
  const mountedRef = useRef(false);

  function persistPendingEvents(candidateEvents: readonly VisualEvent[]): void {
    if (!persistRef.current) return;

    for (const event of candidateEvents) {
      const correlatedConversationId = eventConversationIdsRef.current.get(event.event_id);
      if (
        !correlatedConversationId ||
        persistedEventIdsRef.current.has(event.event_id) ||
        persistenceInFlightRef.current.has(event.event_id)
      ) {
        continue;
      }

      persistenceInFlightRef.current.add(event.event_id);
      void persistVisualEvent(
        correlatedConversationId,
        event,
        eventConnectionStartedAtsRef.current.get(event.event_id) ?? null,
      )
        .then(() => {
          persistedEventIdsRef.current.add(event.event_id);
        })
        .catch((persistenceError: unknown) => {
          if (mountedRef.current) {
            setError(
              persistenceError instanceof Error
                ? persistenceError.message
                : "The visual observation could not be saved.",
            );
          }
        })
        .finally(() => {
          persistenceInFlightRef.current.delete(event.event_id);
        });
    }
  }

  useEffect(() => {
    threadIdRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    persistRef.current = persist;
  }, [persist]);

  useEffect(() => {
    conversationIdRef.current = conversationId;
    connectionStartedAtRef.current = connectionStartedAt;
    if (!conversationId) return;

    for (const event of events) {
      // Capture can be enabled before voice connects. Those earlier observations
      // are useful live UI state but are not evidence from this conversation.
      if (
        !connectionStartedAt ||
        Date.parse(event.occurred_at) < Date.parse(connectionStartedAt)
      ) {
        continue;
      }
      if (!eventConversationIdsRef.current.has(event.event_id)) {
        eventConversationIdsRef.current.set(event.event_id, conversationId);
        eventConnectionStartedAtsRef.current.set(
          event.event_id,
          connectionStartedAt,
        );
      }
    }
    persistPendingEvents(events);
  }, [connectionStartedAt, conversationId, events]);

  const releaseResources = useCallback((): void => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    requestRef.current?.abort();
    requestRef.current = null;
    requestInFlightRef.current = false;

    const track = trackRef.current;
    const endedHandler = trackEndedHandlerRef.current;
    if (track && endedHandler) track.removeEventListener("ended", endedHandler);
    trackEndedHandlerRef.current = null;
    trackRef.current = null;

    streamRef.current?.getTracks().forEach((streamTrack) => streamTrack.stop());
    streamRef.current = null;
    sessionIdRef.current = null;
    eventConversationIdsRef.current.clear();
    eventConnectionStartedAtsRef.current.clear();
    persistedEventIdsRef.current.clear();
    persistenceInFlightRef.current.clear();
    previousFingerprintRef.current = null;
    acceptedFrameRef.current = null;
    acceptedFingerprintRef.current = null;
    lastSentAtRef.current = 0;
    frameIdRef.current = 0;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const stopCapture = useCallback((): void => {
    releaseResources();
    if (mountedRef.current) {
      setEvents([]);
      setError(null);
      setStatus("stopped");
    }
  }, [releaseResources]);

  const captureAndCompare = useCallback(async (): Promise<void> => {
    const video = videoRef.current;
    const sessionId = sessionIdRef.current;
    if (
      !video ||
      !sessionId ||
      !streamRef.current ||
      video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
      requestInFlightRef.current
    ) {
      return;
    }

    requestInFlightRef.current = true;
    let controller: AbortController | null = null;
    const frameId = ++frameIdRef.current;
    const comparisonConversationId = conversationIdRef.current;
    const comparisonConnectionStartedAt = connectionStartedAtRef.current;

    try {
      const currentFrame = await encodeFrame(video, frameId);
      if (currentFrame.blob.size > MAX_FRAME_BYTES) {
        throw new Error(`The captured ${source} frame exceeded the 2 MiB limit.`);
      }
      if (sessionIdRef.current !== sessionId) return;

      const previousFingerprint = previousFingerprintRef.current;
      const previousAcceptedFrame = acceptedFrameRef.current;
      previousFingerprintRef.current = currentFrame.fingerprint;

      if (!previousFingerprint || !previousAcceptedFrame) {
        acceptedFrameRef.current = toTransportFrame(currentFrame);
        acceptedFingerprintRef.current = currentFrame.fingerprint;
        console.debug("visual_baseline_established", { source, sessionId, frameId });
        return;
      }

      const baselineFingerprint =
        profile.baseline === "last-sent"
          ? (acceptedFingerprintRef.current ?? previousFingerprint)
          : previousFingerprint;
      const changeScore = calculateChangeScore(
        baselineFingerprint,
        currentFrame.fingerprint,
      );
      if (
        changeScore.global < profile.globalThreshold &&
        changeScore.block < profile.blockThreshold
      ) {
        console.debug("visual_change_skipped", {
          source,
          sessionId,
          previousFrameId: previousAcceptedFrame.frameId,
          currentFrameId: currentFrame.frameId,
          globalScore: changeScore.global,
          blockScore: changeScore.block,
        });
        return;
      }

      // The cooldown is checked after the pixel test so a quiet camera does not
      // burn its budget, and before the request so continuous motion cannot.
      const elapsedSinceSend = Date.now() - lastSentAtRef.current;
      if (profile.cooldownMs > 0 && elapsedSinceSend < profile.cooldownMs) {
        console.debug("visual_change_throttled", {
          source,
          sessionId,
          currentFrameId: currentFrame.frameId,
          elapsedSinceSend,
        });
        return;
      }

      console.debug("visual_change_detected", {
        source,
        sessionId,
        previousFrameId: previousAcceptedFrame.frameId,
        currentFrameId: currentFrame.frameId,
        globalScore: changeScore.global,
        blockScore: changeScore.block,
      });
      controller = new AbortController();
      requestRef.current = controller;
      lastSentAtRef.current = Date.now();
      if (mountedRef.current) setStatus("processing");

      try {
        const event = await compareVisualFrames(
          {
            previous: previousAcceptedFrame,
            current: toTransportFrame(currentFrame),
            sessionId,
            source,
            changeScore: Math.max(changeScore.global, changeScore.block),
            threadId: threadIdRef.current,
          },
          controller.signal,
        );
        if (mountedRef.current && sessionIdRef.current === sessionId) {
          if (event) {
            if (comparisonConversationId) {
              eventConversationIdsRef.current.set(
                event.event_id,
                comparisonConversationId,
              );
              if (comparisonConnectionStartedAt) {
                eventConnectionStartedAtsRef.current.set(
                  event.event_id,
                  comparisonConnectionStartedAt,
                );
              }
            }
            setEvents((currentEvents) =>
              [...currentEvents, event].slice(-MAX_RECENT_EVENTS),
            );
          }
          setError(null);
        }
      } finally {
        if (sessionIdRef.current === sessionId) {
          // Advance after success, suppression, or failure so a failed pair is not retried.
          acceptedFrameRef.current = toTransportFrame(currentFrame);
          acceptedFingerprintRef.current = currentFrame.fingerprint;
        }
      }
    } catch (requestError) {
      if (
        !controller?.signal.aborted &&
        mountedRef.current &&
        sessionIdRef.current === sessionId
      ) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "The visual change could not be processed.",
        );
      }
    } finally {
      if (sessionIdRef.current === sessionId) {
        if (requestRef.current === controller) requestRef.current = null;
        requestInFlightRef.current = false;
        if (mountedRef.current) setStatus("capturing");
      }
    }
  }, [profile, source]);

  const startCapture = useCallback(async (): Promise<void> => {
    releaseResources();
    setError(null);
    setEvents([]);
    setStatus("requesting");

    if (!isCaptureSupported(source)) {
      setError(
        source === "camera"
          ? "Camera capture is not supported by this browser."
          : "Screen sharing is not supported by this browser.",
      );
      setStatus("error");
      return;
    }

    try {
      // Permission is requested here and nowhere else, so neither input is ever
      // opened until the user presses its own button.
      const stream = await requestStream(source);
      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      const videoTrack = stream.getVideoTracks()[0];
      if (!videoTrack || !videoRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        throw new Error(`The browser did not provide a ${source} video track.`);
      }

      const sessionId = crypto.randomUUID();
      streamRef.current = stream;
      trackRef.current = videoTrack;
      sessionIdRef.current = sessionId;
      const handleTrackEnded = () => stopCapture();
      trackEndedHandlerRef.current = handleTrackEnded;
      videoTrack.addEventListener("ended", handleTrackEnded, { once: true });

      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      if (!streamRef.current || sessionIdRef.current !== sessionId) return;

      setStatus("capturing");
      // Establish the baseline immediately so quick sequences are compared
      // against the state that existed when capture began.
      void captureAndCompare();
      timerRef.current = setInterval(
        () => void captureAndCompare(),
        profile.sampleIntervalMs,
      );
    } catch (captureError) {
      releaseResources();
      if (mountedRef.current) {
        setError(startErrorMessage(captureError, source));
        setStatus("error");
      }
    }
  }, [captureAndCompare, profile.sampleIntervalMs, releaseResources, source, stopCapture]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      releaseResources();
    };
  }, [releaseResources]);

  return {
    error,
    events,
    source,
    startCapture,
    status,
    stopCapture,
    videoRef,
  };
}

export type VisualCaptureController = ReturnType<typeof useVisualCapture>;

function isCaptureSupported(source: VisualSource): boolean {
  if (source === "camera") return Boolean(navigator.mediaDevices?.getUserMedia);
  return Boolean(navigator.mediaDevices?.getDisplayMedia);
}

async function requestStream(source: VisualSource): Promise<MediaStream> {
  if (source === "camera") {
    return navigator.mediaDevices.getUserMedia({
      // The front camera only: audio already belongs to the voice session, and
      // capturing it twice would duplicate the expert's own words.
      video: { facingMode: "user", width: { ideal: 1_280 }, height: { ideal: 720 } },
      audio: false,
    });
  }
  return navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
}

function startErrorMessage(error: unknown, source: VisualSource): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return source === "camera"
        ? "Camera permission was not granted."
        : "Screen-sharing permission was not granted.";
    }
    if (error.name === "NotFoundError" || error.name === "OverconstrainedError") {
      return "No camera was found on this device.";
    }
    if (error.name === "NotReadableError") {
      return "The camera is already in use by another application.";
    }
  }
  if (error instanceof Error) return error.message;
  return source === "camera"
    ? "The camera could not start."
    : "Screen sharing could not start.";
}

async function encodeFrame(
  video: HTMLVideoElement,
  frameId: number,
): Promise<CapturedFrame> {
  const sourceWidth = video.videoWidth;
  const sourceHeight = video.videoHeight;
  if (!sourceWidth || !sourceHeight) {
    throw new Error("The video source is not ready to capture.");
  }

  const scale = Math.min(1, MAX_FRAME_DIMENSION / Math.max(sourceWidth, sourceHeight));
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("The browser could not prepare a frame.");
  context.drawImage(video, 0, 0, width, height);

  const fingerprintCanvas = document.createElement("canvas");
  fingerprintCanvas.width = FINGERPRINT_WIDTH;
  fingerprintCanvas.height = FINGERPRINT_HEIGHT;
  const fingerprintContext = fingerprintCanvas.getContext("2d", {
    willReadFrequently: true,
  });
  if (!fingerprintContext) {
    throw new Error("The browser could not compare frames.");
  }
  fingerprintContext.drawImage(
    canvas,
    0,
    0,
    FINGERPRINT_WIDTH,
    FINGERPRINT_HEIGHT,
  );
  const fingerprint = fingerprintContext.getImageData(
    0,
    0,
    FINGERPRINT_WIDTH,
    FINGERPRINT_HEIGHT,
  ).data;

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (encoded) =>
        encoded
          ? resolve(encoded)
          : reject(new Error("The browser could not encode the frame.")),
      "image/jpeg",
      JPEG_QUALITY,
    );
  });
  return {
    blob,
    frameId,
    capturedAt: new Date().toISOString(),
    width,
    height,
    fingerprint,
  };
}

function calculateChangeScore(
  previous: Uint8ClampedArray,
  current: Uint8ClampedArray,
): { global: number; block: number } {
  if (previous.length !== current.length || previous.length === 0) {
    return { global: 1, block: 1 };
  }

  const blocksPerRow = FINGERPRINT_WIDTH / BLOCK_WIDTH;
  const blockSums = new Float64Array(
    blocksPerRow * (FINGERPRINT_HEIGHT / BLOCK_HEIGHT),
  );
  let total = 0;
  for (let index = 0; index < current.length; index += 4) {
    const difference =
      Math.abs(current[index] - previous[index]) +
      Math.abs(current[index + 1] - previous[index + 1]) +
      Math.abs(current[index + 2] - previous[index + 2]);
    total += difference;
    const pixel = index / 4;
    const x = pixel % FINGERPRINT_WIDTH;
    const y = Math.floor(pixel / FINGERPRINT_WIDTH);
    blockSums[
      Math.floor(y / BLOCK_HEIGHT) * blocksPerRow + Math.floor(x / BLOCK_WIDTH)
    ] += difference;
  }

  const blockNormalizer = BLOCK_WIDTH * BLOCK_HEIGHT * 3 * 255;
  let block = 0;
  for (const sum of blockSums) block = Math.max(block, sum / blockNormalizer);
  return { global: total / ((current.length / 4) * 3 * 255), block };
}

function toTransportFrame(frame: CapturedFrame): VisualFrame {
  return {
    blob: frame.blob,
    frameId: frame.frameId,
    capturedAt: frame.capturedAt,
    width: frame.width,
    height: frame.height,
  };
}
