"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  compareScreenFrames,
  persistScreenEvent,
  type ScreenEvent,
  type ScreenFrame,
} from "@/lib/screen-observation-api";

export type ScreenShareStatus =
  | "idle"
  | "requesting"
  | "sharing"
  | "processing"
  | "stopped"
  | "error";

const SAMPLE_INTERVAL_MS = 500;
const MAX_FRAME_DIMENSION = 1_280;
const JPEG_QUALITY = 0.76;
const MAX_FRAME_BYTES = 2 * 1024 * 1024;
const FINGERPRINT_WIDTH = 192;
const FINGERPRINT_HEIGHT = 108;
const BLOCK_WIDTH = 8;
const BLOCK_HEIGHT = 6;
const VISUAL_CHANGE_THRESHOLD = 0.006;
// A small object (e.g. a recolored sticky note) barely moves the whole-screen
// average, so also gate on the most-changed local block.
const BLOCK_CHANGE_THRESHOLD = 0.06;
const MAX_RECENT_EVENTS = 20;

type CapturedFrame = ScreenFrame & {
  fingerprint: Uint8ClampedArray;
};

export function useScreenShare(threadId?: string, conversationId?: string | null) {
  const [status, setStatus] = useState<ScreenShareStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<ScreenEvent[]>([]);
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
  const eventConversationIdsRef = useRef(new Map<string, string>());
  const persistedEventIdsRef = useRef(new Set<string>());
  const persistenceInFlightRef = useRef(new Set<string>());
  const previousFingerprintRef = useRef<Uint8ClampedArray | null>(null);
  const acceptedFrameRef = useRef<ScreenFrame | null>(null);
  const mountedRef = useRef(false);

  function persistPendingEvents(candidateEvents: readonly ScreenEvent[]): void {
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
      void persistScreenEvent(correlatedConversationId, event)
        .then(() => {
          persistedEventIdsRef.current.add(event.event_id);
        })
        .catch((persistenceError: unknown) => {
          if (mountedRef.current) {
            setError(
              persistenceError instanceof Error
                ? persistenceError.message
                : "The screen observation could not be saved.",
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
    conversationIdRef.current = conversationId;
    if (!conversationId) return;

    for (const event of events) {
      if (!eventConversationIdsRef.current.has(event.event_id)) {
        eventConversationIdsRef.current.set(event.event_id, conversationId);
      }
    }
    persistPendingEvents(events);
  }, [conversationId, events]);

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
    persistedEventIdsRef.current.clear();
    persistenceInFlightRef.current.clear();
    previousFingerprintRef.current = null;
    acceptedFrameRef.current = null;
    frameIdRef.current = 0;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const stopSharing = useCallback((): void => {
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

    try {
      const currentFrame = await encodeFrame(video, frameId);
      if (currentFrame.blob.size > MAX_FRAME_BYTES) {
        throw new Error("The captured screen frame exceeded the 2 MiB limit.");
      }
      if (sessionIdRef.current !== sessionId) return;

      const previousFingerprint = previousFingerprintRef.current;
      const previousAcceptedFrame = acceptedFrameRef.current;
      previousFingerprintRef.current = currentFrame.fingerprint;

      if (!previousFingerprint || !previousAcceptedFrame) {
        acceptedFrameRef.current = toTransportFrame(currentFrame);
        console.debug("screen_baseline_established", { sessionId, frameId });
        return;
      }

      const changeScore = calculateChangeScore(
        previousFingerprint,
        currentFrame.fingerprint,
      );
      if (
        changeScore.global < VISUAL_CHANGE_THRESHOLD &&
        changeScore.block < BLOCK_CHANGE_THRESHOLD
      ) {
        console.debug("screen_change_skipped", {
          sessionId,
          previousFrameId: previousAcceptedFrame.frameId,
          currentFrameId: currentFrame.frameId,
          globalScore: changeScore.global,
          blockScore: changeScore.block,
        });
        return;
      }

      console.debug("screen_change_detected", {
        sessionId,
        previousFrameId: previousAcceptedFrame.frameId,
        currentFrameId: currentFrame.frameId,
        globalScore: changeScore.global,
        blockScore: changeScore.block,
      });
      controller = new AbortController();
      requestRef.current = controller;
      if (mountedRef.current) setStatus("processing");

      try {
        const event = await compareScreenFrames(
          {
            previous: previousAcceptedFrame,
            current: toTransportFrame(currentFrame),
            sessionId,
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
            : "The screen change could not be processed.",
        );
      }
    } finally {
      if (sessionIdRef.current === sessionId) {
        if (requestRef.current === controller) requestRef.current = null;
        requestInFlightRef.current = false;
        if (mountedRef.current) setStatus("sharing");
      }
    }
  }, []);

  const startSharing = useCallback(async (): Promise<void> => {
    releaseResources();
    setError(null);
    setEvents([]);
    setStatus("requesting");

    if (!navigator.mediaDevices?.getDisplayMedia) {
      setError("Screen sharing is not supported by this browser.");
      setStatus("error");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      });
      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      const videoTrack = stream.getVideoTracks()[0];
      if (!videoTrack || !videoRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        throw new Error("The browser did not provide a screen video track.");
      }

      const sessionId = crypto.randomUUID();
      streamRef.current = stream;
      trackRef.current = videoTrack;
      sessionIdRef.current = sessionId;
      const handleTrackEnded = () => stopSharing();
      trackEndedHandlerRef.current = handleTrackEnded;
      videoTrack.addEventListener("ended", handleTrackEnded, { once: true });

      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      if (!streamRef.current || sessionIdRef.current !== sessionId) return;

      setStatus("sharing");
      // Establish the baseline immediately so quick create-and-type sequences are
      // compared against the screen that existed when sharing began.
      void captureAndCompare();
      timerRef.current = setInterval(
        () => void captureAndCompare(),
        SAMPLE_INTERVAL_MS,
      );
    } catch (captureError) {
      releaseResources();
      if (mountedRef.current) {
        setError(
          captureError instanceof DOMException && captureError.name === "NotAllowedError"
            ? "Screen-sharing permission was not granted."
            : captureError instanceof Error
              ? captureError.message
              : "Screen sharing could not start.",
        );
        setStatus("error");
      }
    }
  }, [captureAndCompare, releaseResources, stopSharing]);

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
    startSharing,
    status,
    stopSharing,
    videoRef,
  };
}

async function encodeFrame(
  video: HTMLVideoElement,
  frameId: number,
): Promise<CapturedFrame> {
  const sourceWidth = video.videoWidth;
  const sourceHeight = video.videoHeight;
  if (!sourceWidth || !sourceHeight) {
    throw new Error("The shared screen is not ready to capture.");
  }

  const scale = Math.min(1, MAX_FRAME_DIMENSION / Math.max(sourceWidth, sourceHeight));
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("The browser could not prepare a screen frame.");
  context.drawImage(video, 0, 0, width, height);

  const fingerprintCanvas = document.createElement("canvas");
  fingerprintCanvas.width = FINGERPRINT_WIDTH;
  fingerprintCanvas.height = FINGERPRINT_HEIGHT;
  const fingerprintContext = fingerprintCanvas.getContext("2d", {
    willReadFrequently: true,
  });
  if (!fingerprintContext) {
    throw new Error("The browser could not compare screen frames.");
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
          : reject(new Error("The browser could not encode the screen frame.")),
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

function toTransportFrame(frame: CapturedFrame): ScreenFrame {
  return {
    blob: frame.blob,
    frameId: frame.frameId,
    capturedAt: frame.capturedAt,
    width: frame.width,
    height: frame.height,
  };
}
