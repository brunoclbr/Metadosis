"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  sendScreenFrame,
  type ScreenObservation,
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

export function useScreenShare(threadId?: string) {
  const [status, setStatus] = useState<ScreenShareStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [observation, setObservation] = useState<ScreenObservation | null>(null);
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
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const stopSharing = useCallback((): void => {
    releaseResources();
    if (mountedRef.current) setStatus("stopped");
  }, [releaseResources]);

  const captureAndSend = useCallback(async (): Promise<void> => {
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
    if (mountedRef.current) setStatus("processing");
    const controller = new AbortController();
    requestRef.current = controller;
    const frameId = ++frameIdRef.current;

    try {
      const capturedAt = new Date().toISOString();
      const frame = await encodeFrame(video);
      if (frame.blob.size > MAX_FRAME_BYTES) {
        throw new Error("The captured screen frame exceeded the 2 MiB limit.");
      }
      const result = await sendScreenFrame(
        {
          ...frame,
          sessionId,
          frameId,
          capturedAt,
          threadId: threadIdRef.current,
        },
        controller.signal,
      );
      if (mountedRef.current && sessionIdRef.current === sessionId) {
        setObservation(result);
        setError(null);
      }
    } catch (requestError) {
      if (!controller.signal.aborted && mountedRef.current) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "The screen frame could not be processed.",
        );
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        requestInFlightRef.current = false;
        if (mountedRef.current && sessionIdRef.current === sessionId) {
          setStatus("sharing");
        }
      }
    }
  }, []);

  const startSharing = useCallback(async (): Promise<void> => {
    releaseResources();
    setError(null);
    setObservation(null);
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
      frameIdRef.current = 0;
      const handleTrackEnded = () => stopSharing();
      trackEndedHandlerRef.current = handleTrackEnded;
      videoTrack.addEventListener("ended", handleTrackEnded, { once: true });

      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      if (!streamRef.current || sessionIdRef.current !== sessionId) return;

      setStatus("sharing");
      timerRef.current = setInterval(
        () => void captureAndSend(),
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
  }, [captureAndSend, releaseResources, stopSharing]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      releaseResources();
    };
  }, [releaseResources]);

  return {
    error,
    observation,
    startSharing,
    status,
    stopSharing,
    videoRef,
  };
}

async function encodeFrame(
  video: HTMLVideoElement,
): Promise<{ blob: Blob; width: number; height: number }> {
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
  return { blob, width, height };
}
