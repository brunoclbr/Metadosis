"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createProcess, listProcesses, type Process } from "@/lib/process-api";

export function useProcesses() {
  const [processes, setProcesses] = useState<Process[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const mountedRef = useRef(false);

  // A newly created Process is prepended locally rather than refetched: the
  // caller needs its ID immediately to start a session with it.
  const addProcess = useCallback(
    async (title: string, description?: string): Promise<Process | null> => {
      setIsCreating(true);
      try {
        const created = await createProcess(title, description);
        if (!mountedRef.current) return created;
        setProcesses((current) =>
          current.some((item) => item.id === created.id)
            ? current
            : [created, ...current],
        );
        setError(null);
        return created;
      } catch (createError) {
        if (mountedRef.current) {
          setError(
            createError instanceof Error
              ? createError.message
              : "The process could not be created.",
          );
        }
        return null;
      } finally {
        if (mountedRef.current) setIsCreating(false);
      }
    },
    [],
  );

  // State is updated from the fetch callbacks rather than the effect body so the
  // initial load does not trigger a cascading render.
  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();

    listProcesses(controller.signal)
      .then((loaded) => {
        if (!mountedRef.current) return;
        setProcesses(loaded);
        setError(null);
      })
      .catch((loadError: unknown) => {
        if (!mountedRef.current || isAbortError(loadError)) return;
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Processes could not be loaded.",
        );
      })
      .finally(() => {
        if (mountedRef.current) setIsLoading(false);
      });

    return () => {
      mountedRef.current = false;
      controller.abort();
    };
  }, []);

  return { addProcess, error, isCreating, isLoading, processes };
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
