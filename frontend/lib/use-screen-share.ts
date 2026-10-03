"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  compareScreenFrames,
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

const SAMPLE_INTERVAL_MS = 2_000;
const MAX_FRAME_DIMENSION = 1_280;
const JPEG_QUALITY = 0.76;
const MAX_FRAME_BYTES = 2 * 1024 * 1024;
const FINGERPRINT_WIDTH = 96;
const FINGERPRINT_HEIGHT = 54;
const VISUAL_CHANGE_THRESHOLD = 0.006;
const MAX_RECENT_EVENTS = 20;

type CapturedFrame = ScreenFrame & {
  fingerprint: Uint8ClampedArray;
};

export function useScreenShare(threadId?: string) {
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
  const previousFingerprintRef = useRef<Uint8ClampedArray | null>(null);
  const acceptedFrameRef = useRef<ScreenFrame | null>(null);
  const mountedRef = useRef(false);

  useEffect(() => {
    threadIdRef.current = threadId;
  }, [threadId]);

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
      if (changeScore < VISUAL_CHANGE_THRESHOLD) {
        console.debug("screen_change_skipped", {
          sessionId,
          previousFrameId: previousAcceptedFrame.frameId,
          currentFrameId: currentFrame.frameId,
          changeScore,
        });
        return;
      }

      console.debug("screen_change_detected", {
        sessionId,
        previousFrameId: previousAcceptedFrame.frameId,
        currentFrameId: currentFrame.frameId,
        changeScore,
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
            changeScore,
            threadId: threadIdRef.current,
          },
          controller.signal,
        );
        if (mountedRef.current && sessionIdRef.current === sessionId) {
          if (event) {
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
): number {
  if (previous.length !== current.length || previous.length === 0) return 1;

  let difference = 0;
  for (let index = 0; index < current.length; index += 4) {
    difference += Math.abs(current[index] - previous[index]);
    difference += Math.abs(current[index + 1] - previous[index + 1]);
    difference += Math.abs(current[index + 2] - previous[index + 2]);
  }
  return difference / ((current.length / 4) * 3 * 255);
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
