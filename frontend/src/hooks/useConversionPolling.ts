import { useCallback, useEffect, useRef, useState } from "react";

import { getConversion } from "../api/client";
import type { ConversionStatusResponse } from "../types";

const POLL_INTERVAL_MS = 2000;

type PollingError = string | null;
type TimeoutId = ReturnType<typeof setTimeout>;

function isTerminalConversionStatus(
  status: ConversionStatusResponse["status"],
): boolean {
  return status === "conversion_ready" || status === "failed";
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Failed to fetch conversion status";
}

export function useConversionPolling(
  conversionId: string | null | undefined,
): {
  conversion: ConversionStatusResponse | null;
  error: PollingError;
} {
  const [conversion, setConversion] =
    useState<ConversionStatusResponse | null>(null);
  const [error, setError] = useState<PollingError>(null);
  const timeoutRef = useRef<TimeoutId | null>(null);
  const pollingTokenRef = useRef(0);

  const clearPollingTimeout = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const pollConversion = useCallback(async (pollingToken: number) => {
    if (!conversionId) {
      clearPollingTimeout();
      return;
    }

    clearPollingTimeout();

    try {
      const nextConversion = await getConversion(conversionId);

      if (pollingTokenRef.current !== pollingToken) {
        return;
      }

      setConversion(nextConversion);
      setError(null);

      if (!isTerminalConversionStatus(nextConversion.status)) {
        timeoutRef.current = setTimeout(() => {
          void pollConversion(pollingToken);
        }, POLL_INTERVAL_MS);
      }
    } catch (pollError) {
      if (pollingTokenRef.current !== pollingToken) {
        return;
      }

      clearPollingTimeout();
      setError(getErrorMessage(pollError));
    }
  }, [clearPollingTimeout, conversionId]);

  useEffect(() => {
    pollingTokenRef.current += 1;
    const pollingToken = pollingTokenRef.current;
    const cleanupPolling = () => {
      if (pollingTokenRef.current === pollingToken) {
        pollingTokenRef.current += 1;
      }

      clearPollingTimeout();
    };

    setConversion(null);
    setError(null);
    clearPollingTimeout();

    if (!conversionId) {
      return cleanupPolling;
    }

    void pollConversion(pollingToken);

    return cleanupPolling;
  }, [clearPollingTimeout, conversionId, pollConversion]);

  return { conversion, error };
}
