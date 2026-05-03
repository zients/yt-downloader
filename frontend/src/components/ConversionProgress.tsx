import { useEffect, useRef } from "react";

import type { ConversionStatusResponse } from "../types";

const downloadedConversionIds = new Set<string>();

type ConversionProgressProps = {
  autoDownload?: boolean;
  conversion: ConversionStatusResponse;
  onAutoDownload?: (conversionId: string) => void;
};

export function ConversionProgress({
  autoDownload = true,
  conversion,
  onAutoDownload,
}: ConversionProgressProps) {
  const downloadedConversionIdRef = useRef<string | null>(null);
  const isReady =
    conversion.status === "conversion_ready" && Boolean(conversion.download_url);
  const isFailed = conversion.status === "failed";
  const progress = conversion.progress ?? 0;
  const message = conversion.message ?? "Converting";

  useEffect(() => {
    if (
      conversion.status === "conversion_ready" &&
      conversion.download_url &&
      autoDownload &&
      downloadedConversionIdRef.current !== conversion.conversion_id &&
      !downloadedConversionIds.has(conversion.conversion_id)
    ) {
      downloadedConversionIdRef.current = conversion.conversion_id;
      downloadedConversionIds.add(conversion.conversion_id);
      onAutoDownload?.(conversion.conversion_id);
      window.location.assign(conversion.download_url);
    }
  }, [autoDownload, conversion, onAutoDownload]);

  if (isReady) {
    return (
      <section className="conversion ready" aria-live="polite">
        <p>Conversion complete</p>
        <a className="download-link" href={conversion.download_url ?? undefined}>
          Download file
        </a>
      </section>
    );
  }

  if (isFailed) {
    return (
      <section className="conversion failed" aria-live="polite">
        <p>{conversion.error ?? "Conversion failed"}</p>
      </section>
    );
  }

  return (
    <section className="conversion" aria-live="polite">
      <p>{message}</p>
      <div
        className="progress-bar"
        aria-label={`Conversion progress ${progress}%`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={progress}
        role="progressbar"
      >
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>
    </section>
  );
}
