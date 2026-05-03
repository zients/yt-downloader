import { useEffect, useState } from "react";

import { createTask } from "./api/client";
import { JobCard } from "./components/JobCard";
import { UrlInput } from "./components/UrlInput";
import {
  addRecentJob,
  hydrateRecentJobs,
  markRecentJobAutoDownloaded,
  RECENT_JOBS_STORAGE_KEY,
  removeRecentJob,
  serializeRecentJobs,
  updateRecentJobConversion,
  type RecentJob,
} from "./recentJobs";

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function readStoredJobs(): RecentJob[] {
  try {
    return hydrateRecentJobs(
      window.localStorage.getItem(RECENT_JOBS_STORAGE_KEY),
    );
  } catch {
    return [];
  }
}

function writeStoredJobs(jobs: RecentJob[]) {
  try {
    window.localStorage.setItem(
      RECENT_JOBS_STORAGE_KEY,
      serializeRecentJobs(jobs),
    );
  } catch {
    // Ignore storage failures so the downloader remains usable.
  }
}

function App() {
  const [jobs, setJobs] = useState<RecentJob[]>(readStoredJobs);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    writeStoredJobs(jobs);
  }, [jobs]);

  async function handleUrlSubmit(url: string) {
    if (isSubmitting) {
      return;
    }

    setSubmitError(null);
    setIsSubmitting(true);

    try {
      const createdTask = await createTask(url);
      setJobs((currentJobs) => addRecentJob(currentJobs, createdTask.task_id));
    } catch (error) {
      setSubmitError(getErrorMessage(error, "Failed to submit URL"));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleConversionCreated(taskId: string, conversionId: string) {
    setJobs((currentJobs) =>
      updateRecentJobConversion(currentJobs, taskId, conversionId),
    );
  }

  function handleConversionAutoDownloaded(taskId: string, conversionId: string) {
    setJobs((currentJobs) => {
      const nextJobs = markRecentJobAutoDownloaded(
        currentJobs,
        taskId,
        conversionId,
      );
      writeStoredJobs(nextJobs);
      return nextJobs;
    });
  }

  function handleRemoveJob(taskId: string) {
    setJobs((currentJobs) => removeRecentJob(currentJobs, taskId));
  }

  return (
    <div className="app-shell">
      <main className="app-main">
        <header className="app-header">
          <h1>YT Downloader</h1>
        </header>

        <UrlInput disabled={isSubmitting} onSubmit={handleUrlSubmit} />

        {submitError ? (
          <section className="error-banner" role="alert">
            <span>{submitError}</span>
            <button onClick={() => setSubmitError(null)} type="button">
              Dismiss
            </button>
          </section>
        ) : null}

        {jobs.length > 0 ? (
          <section className="jobs-list" aria-label="Recent downloads">
            {jobs.map((job) => (
              <JobCard
                job={job}
                key={job.taskId}
                onConversionAutoDownloaded={handleConversionAutoDownloaded}
                onConversionCreated={handleConversionCreated}
                onRemove={handleRemoveJob}
              />
            ))}
          </section>
        ) : null}
      </main>
    </div>
  );
}

export default App;
