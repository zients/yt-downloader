import { useState } from "react";

import { createConversion, createTask } from "./api/client";
import { ConversionProgress } from "./components/ConversionProgress";
import { FormatSelector } from "./components/FormatSelector";
import { TaskProgress } from "./components/TaskProgress";
import { UrlInput } from "./components/UrlInput";
import { useConversionPolling } from "./hooks/useConversionPolling";
import { useTaskPolling } from "./hooks/useTaskPolling";
import type { FormatPreset } from "./types";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function App() {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [conversionId, setConversionId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCreatingConversion, setIsCreatingConversion] = useState(false);
  const { task, error: taskError } = useTaskPolling(taskId);
  const { conversion, error: conversionError } =
    useConversionPolling(conversionId);

  const currentTask = task?.task_id === taskId ? task : null;
  const currentConversion =
    conversion?.conversion_id === conversionId ? conversion : null;
  const isAwaitingTaskStatus = Boolean(taskId) && !currentTask;
  const isAwaitingConversionStatus = Boolean(conversionId) && !currentConversion;
  const isSourceProcessing =
    isSubmitting ||
    isAwaitingTaskStatus ||
    currentTask?.status === "source_pending" ||
    currentTask?.status === "source_processing";
  const conversionProcessing =
    isCreatingConversion ||
    isAwaitingConversionStatus ||
    currentConversion?.status === "conversion_pending" ||
    currentConversion?.status === "conversion_processing";
  const isSourceReady = currentTask?.status === "source_ready";
  const isAppBusy = isSourceProcessing || conversionProcessing;
  const visibleError =
    submitError ??
    taskError ??
    conversionError ??
    currentTask?.error ??
    currentConversion?.error ??
    null;

  async function handleUrlSubmit(url: string) {
    if (isAppBusy) {
      return;
    }

    setTaskId(null);
    setConversionId(null);
    setSubmitError(null);
    setIsCreatingConversion(false);
    setIsSubmitting(true);

    try {
      const createdTask = await createTask(url);
      setTaskId(createdTask.task_id);
    } catch (error) {
      setSubmitError(getErrorMessage(error, "Failed to submit URL"));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handlePresetSelect(preset: FormatPreset) {
    if (
      !currentTask ||
      currentTask.status !== "source_ready" ||
      conversionProcessing
    ) {
      return;
    }

    setConversionId(null);
    setSubmitError(null);
    setIsCreatingConversion(true);

    try {
      const createdConversion = await createConversion(
        currentTask.task_id,
        preset.format,
        preset.quality ?? null,
      );
      setConversionId(createdConversion.conversion_id);
    } catch (error) {
      setSubmitError(getErrorMessage(error, "Failed to create conversion"));
    } finally {
      setIsCreatingConversion(false);
    }
  }

  function handleReset() {
    setTaskId(null);
    setConversionId(null);
    setSubmitError(null);
    setIsSubmitting(false);
    setIsCreatingConversion(false);
  }

  return (
    <div className="app-shell">
      <main className="app-main">
        <header className="app-header">
          <h1>YT Downloader</h1>
        </header>

        <UrlInput disabled={isAppBusy} onSubmit={handleUrlSubmit} />

        {visibleError ? (
          <section className="error-banner" role="alert">
            <span>{visibleError}</span>
            <button onClick={handleReset} type="button">
              Reset
            </button>
          </section>
        ) : null}

        {currentTask &&
          currentTask.status !== "source_ready" &&
          currentTask.status !== "failed" ? (
          <TaskProgress task={currentTask} />
        ) : null}

        {isSourceReady ? (
          <section className="panel ready-panel">
            <h2>{currentTask.title ?? "Video ready"}</h2>
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
                onSelect={handlePresetSelect}
                presets={currentTask.output_presets}
              />
            ) : null}
          </section>
        ) : null}

        {currentConversion ? (
          <ConversionProgress conversion={currentConversion} />
        ) : null}
      </main>
    </div>
  );
}

export default App;
