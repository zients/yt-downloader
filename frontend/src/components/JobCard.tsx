import { useEffect, useState } from "react";

import { createConversion } from "../api/client";
import {
  findMatchingPreset,
  flattenAvailablePresets,
  getDefaultFormatPreset,
  presetsMatch,
} from "../formatPresets";
import { useConversionPolling } from "../hooks/useConversionPolling";
import { useTaskPolling } from "../hooks/useTaskPolling";
import { isExpiredRecentJobError, type RecentJob } from "../recentJobs";
import type { FormatPreset } from "../types";
import { ConversionProgress } from "./ConversionProgress";
import { FormatSelector } from "./FormatSelector";
import { TaskProgress } from "./TaskProgress";

type JobCardProps = {
  job: RecentJob;
  onConversionAutoDownloaded: (taskId: string, conversionId: string) => void;
  onConversionCreated: (
    taskId: string,
    conversionId: string,
    conversionPreset: FormatPreset,
  ) => void;
  onRemove: (taskId: string) => void;
};

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function formatSubmittedAt(timestamp: number): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

export function JobCard({
  job,
  onConversionAutoDownloaded,
  onConversionCreated,
  onRemove,
}: JobCardProps) {
  const [conversionCreateError, setConversionCreateError] = useState<
    string | null
  >(null);
  const [isCreatingConversion, setIsCreatingConversion] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState<FormatPreset | null>(
    job.conversionPreset ?? null,
  );
  const { task, error: taskError } = useTaskPolling(job.taskId);
  const { conversion, error: conversionError } = useConversionPolling(
    job.conversionId,
  );

  const currentTask = task?.task_id === job.taskId ? task : null;
  const currentConversion =
    conversion?.conversion_id === job.conversionId ? conversion : null;
  const autoDownloadedCurrentConversion =
    currentConversion !== null &&
    job.autoDownloadedConversionId === currentConversion.conversion_id;
  const isAwaitingTaskStatus = !currentTask && !taskError;
  const isAwaitingConversionStatus =
    Boolean(job.conversionId) && !currentConversion && !conversionError;
  const conversionProcessing =
    isCreatingConversion ||
    isAwaitingConversionStatus ||
    currentConversion?.status === "conversion_pending" ||
    currentConversion?.status === "conversion_processing";
  const isSourceReady = currentTask?.status === "source_ready";
  const cardTitle =
    currentTask?.title ??
    (taskError ? "Video unavailable" : "Preparing video");
  const taskFailed = currentTask?.status === "failed";
  const cardError =
    taskError ??
    conversionCreateError ??
    conversionError ??
    (taskFailed ? currentTask?.error ?? "Source download failed" : null);
  const outputPresets = currentTask?.output_presets ?? null;
  const availablePresets = flattenAvailablePresets(outputPresets);
  const selectedAvailablePreset = findMatchingPreset(
    availablePresets,
    selectedPreset,
  );
  const activeSelectedPreset =
    selectedAvailablePreset ?? getDefaultFormatPreset(outputPresets);
  const currentConversionMatchesSelection =
    !job.conversionPreset ||
    presetsMatch(job.conversionPreset, activeSelectedPreset);

  useEffect(() => {
    if (
      isExpiredRecentJobError(taskError) ||
      isExpiredRecentJobError(conversionError)
    ) {
      onRemove(job.taskId);
    }
  }, [conversionError, job.taskId, onRemove, taskError]);

  useEffect(() => {
    if (!outputPresets) {
      return;
    }

    const nextAvailablePresets = flattenAvailablePresets(outputPresets);

    setSelectedPreset((currentSelectedPreset) => {
      if (
        currentSelectedPreset &&
        findMatchingPreset(nextAvailablePresets, currentSelectedPreset)
      ) {
        return currentSelectedPreset;
      }

      return getDefaultFormatPreset(outputPresets);
    });
  }, [outputPresets]);

  async function handleConvertClick() {
    if (
      !currentTask ||
      currentTask.status !== "source_ready" ||
      conversionProcessing ||
      !activeSelectedPreset
    ) {
      return;
    }

    setConversionCreateError(null);
    setIsCreatingConversion(true);

    try {
      const createdConversion = await createConversion(
        currentTask.task_id,
        activeSelectedPreset.format,
        activeSelectedPreset.quality ?? null,
      );
      onConversionCreated(
        currentTask.task_id,
        createdConversion.conversion_id,
        activeSelectedPreset,
      );
    } catch (error) {
      setConversionCreateError(
        getErrorMessage(error, "Failed to create conversion"),
      );
    } finally {
      setIsCreatingConversion(false);
    }
  }

  return (
    <article className="job-card">
      <header className="job-card-header">
        <div>
          <h2>{cardTitle}</h2>
          <p>Submitted {formatSubmittedAt(job.createdAt)}</p>
        </div>
        <button onClick={() => onRemove(job.taskId)} type="button">
          Remove
        </button>
      </header>

      {cardError ? (
        <section className="job-card-error" role="alert">
          {cardError}
        </section>
      ) : null}

      {isAwaitingTaskStatus ? (
        <section className="job-card-status" aria-live="polite">
          Restoring video status...
        </section>
      ) : null}

      {currentTask &&
      currentTask.status !== "source_ready" &&
      currentTask.status !== "failed" ? (
        <TaskProgress task={currentTask} />
      ) : null}

      {isSourceReady ? (
        <section className="ready-panel">
          {currentTask.thumbnail ? (
            <img
              className="thumbnail"
              src={currentTask.thumbnail}
              alt={currentTask.title ?? "Video thumbnail"}
            />
          ) : null}
          {currentTask.output_presets ? (
            <FormatSelector
              disabled={conversionProcessing}
              onChange={setSelectedPreset}
              presets={currentTask.output_presets}
              selectedPreset={activeSelectedPreset}
            />
          ) : null}
          <button
            className="convert-button"
            disabled={conversionProcessing || !activeSelectedPreset}
            onClick={handleConvertClick}
            type="button"
          >
            Convert
          </button>
        </section>
      ) : null}

      {isAwaitingConversionStatus ? (
        <section className="job-card-status" aria-live="polite">
          Restoring conversion status...
        </section>
      ) : null}

      {currentConversion && currentConversionMatchesSelection ? (
        <ConversionProgress
          autoDownload={!autoDownloadedCurrentConversion}
          conversion={currentConversion}
          onAutoDownload={(conversionId) =>
            onConversionAutoDownloaded(job.taskId, conversionId)
          }
        />
      ) : null}
    </article>
  );
}
