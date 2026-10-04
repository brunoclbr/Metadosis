"use client";

import { useCallback, useEffect, useState } from "react";

import {
  BrainGraphError,
  getBrainGraph,
  type BrainGraph,
} from "@/lib/brain-graph-api";

type GraphRequestState = {
  error: string | null;
  graph: BrainGraph | null;
  isEmpty: boolean;
  processId: string | null;
  requestKey: number;
};

export function useBrainGraph(processId: string | null, enabled: boolean) {
  const [requestKey, setRequestKey] = useState(0);
  const [state, setState] = useState<GraphRequestState>({
    error: null,
    graph: null,
    isEmpty: false,
    processId: null,
    requestKey: -1,
  });

  const retry = useCallback(() => setRequestKey((current) => current + 1), []);

  useEffect(() => {
    if (!processId || !enabled) return;

    const controller = new AbortController();
    getBrainGraph(processId, controller.signal)
      .then((graph) => {
        setState({ error: null, graph, isEmpty: false, processId, requestKey });
      })
      .catch((loadError: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          error:
            loadError instanceof BrainGraphError && loadError.status === 404
              ? null
              : "The Brain couldn't be loaded.",
          graph: null,
          isEmpty:
            loadError instanceof BrainGraphError && loadError.status === 404,
          processId,
          requestKey,
        });
      });

    return () => controller.abort();
  }, [enabled, processId, requestKey]);

  const isCurrent =
    state.processId === processId && state.requestKey === requestKey;
  return {
    error: isCurrent ? state.error : null,
    graph: isCurrent ? state.graph : null,
    isEmpty: isCurrent && state.isEmpty,
    isLoading: Boolean(enabled && processId && !isCurrent),
    retry,
  };
}
