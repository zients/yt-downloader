import { useCallback, useEffect, useRef, useState } from "react";

import { getTask } from "../api/client";
import type { TaskStatusResponse } from "../types";

const POLL_INTERVAL_MS = 2000;

type PollingError = string | null;
type TimeoutId = ReturnType<typeof setTimeout>;

function isTerminalTaskStatus(status: TaskStatusResponse["status"]): boolean {
  return status === "source_ready" || status === "failed";
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Failed to fetch task status";
}

export function useTaskPolling(taskId: string | null | undefined): {
  task: TaskStatusResponse | null;
  error: PollingError;
} {
  const [task, setTask] = useState<TaskStatusResponse | null>(null);
  const [error, setError] = useState<PollingError>(null);
  const timeoutRef = useRef<TimeoutId | null>(null);
  const pollingTokenRef = useRef(0);

  const clearPollingTimeout = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const pollTask = useCallback(async (pollingToken: number) => {
    if (!taskId) {
      clearPollingTimeout();
      return;
    }

    clearPollingTimeout();

    try {
      const nextTask = await getTask(taskId);

      if (pollingTokenRef.current !== pollingToken) {
        return;
      }

      setTask(nextTask);
      setError(null);

      if (!isTerminalTaskStatus(nextTask.status)) {
        timeoutRef.current = setTimeout(() => {
          void pollTask(pollingToken);
        }, POLL_INTERVAL_MS);
      }
    } catch (pollError) {
      if (pollingTokenRef.current !== pollingToken) {
        return;
      }

      clearPollingTimeout();
      setError(getErrorMessage(pollError));
    }
  }, [clearPollingTimeout, taskId]);

  useEffect(() => {
    pollingTokenRef.current += 1;
    const pollingToken = pollingTokenRef.current;
    const cleanupPolling = () => {
      if (pollingTokenRef.current === pollingToken) {
        pollingTokenRef.current += 1;
      }

      clearPollingTimeout();
    };

    setTask(null);
    setError(null);
    clearPollingTimeout();

    if (!taskId) {
      return cleanupPolling;
    }

    void pollTask(pollingToken);

    return cleanupPolling;
  }, [clearPollingTimeout, pollTask, taskId]);

  return { task, error };
}
