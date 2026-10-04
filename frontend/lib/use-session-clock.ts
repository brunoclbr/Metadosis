"use client";

import { useEffect, useState } from "react";

/**
 * How long the live session has been running, as `hh:mm:ss`.
 *
 * The elapsed time is derived from the connection timestamp on every render
 * rather than counted up in state, so a re-render or a briefly backgrounded tab
 * cannot drift the clock. The effect only subscribes to the passing second.
 * Returns null whenever no session is connected.
 */
export function useSessionClock(connectionStartedAt: string | null): string | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!connectionStartedAt) return;

    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [connectionStartedAt]);

  if (!connectionStartedAt) return null;

  const startedAt = Date.parse(connectionStartedAt);
  if (!Number.isFinite(startedAt)) return null;

  // A session that has just connected can be ahead of the last tick; it reads
  // as 00:00:00 until the next second arrives.
  return formatDuration(Math.max(0, now - startedAt));
}

function formatDuration(elapsedMs: number): string {
  const totalSeconds = Math.floor(elapsedMs / 1_000);
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}
