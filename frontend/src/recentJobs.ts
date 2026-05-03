export const RECENT_JOBS_LIMIT = 5;
export const RECENT_JOBS_STORAGE_KEY = "yt-downloader:recent-jobs";

export type RecentJob = {
  taskId: string;
  conversionId?: string;
  autoDownloadedConversionId?: string;
  createdAt: number;
  updatedAt: number;
};

type StoredRecentJob = {
  taskId?: unknown;
  conversionId?: unknown;
  autoDownloadedConversionId?: unknown;
  createdAt?: unknown;
  updatedAt?: unknown;
};

function isObject(value: unknown): value is StoredRecentJob {
  return typeof value === "object" && value !== null;
}

function readTimestamp(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function trimRecentJobs(jobs: RecentJob[]): RecentJob[] {
  return jobs.slice(0, RECENT_JOBS_LIMIT);
}

export function addRecentJob(
  jobs: RecentJob[],
  taskId: string,
  timestamp = Date.now(),
): RecentJob[] {
  const existingJob = jobs.find((job) => job.taskId === taskId);
  const nextJob: RecentJob = {
    taskId,
    createdAt: existingJob?.createdAt ?? timestamp,
    updatedAt: timestamp,
    ...(existingJob?.conversionId
      ? { conversionId: existingJob.conversionId }
      : {}),
  };

  return trimRecentJobs([
    nextJob,
    ...jobs.filter((job) => job.taskId !== taskId),
  ]);
}

export function updateRecentJobConversion(
  jobs: RecentJob[],
  taskId: string,
  conversionId: string,
  timestamp = Date.now(),
): RecentJob[] {
  return jobs.map((job) =>
    job.taskId === taskId
      ? {
          ...job,
          conversionId,
          ...(job.autoDownloadedConversionId === conversionId
            ? { autoDownloadedConversionId: job.autoDownloadedConversionId }
            : { autoDownloadedConversionId: undefined }),
          updatedAt: timestamp,
        }
      : job,
  );
}

export function markRecentJobAutoDownloaded(
  jobs: RecentJob[],
  taskId: string,
  conversionId: string,
  timestamp = Date.now(),
): RecentJob[] {
  return jobs.map((job) =>
    job.taskId === taskId
      ? {
          ...job,
          conversionId,
          autoDownloadedConversionId: conversionId,
          updatedAt: timestamp,
        }
      : job,
  );
}

export function removeRecentJob(
  jobs: RecentJob[],
  taskId: string,
): RecentJob[] {
  return jobs.filter((job) => job.taskId !== taskId);
}

export function hydrateRecentJobs(serialized: string | null): RecentJob[] {
  if (!serialized) {
    return [];
  }

  try {
    const parsed = JSON.parse(serialized) as unknown;

    if (!Array.isArray(parsed)) {
      return [];
    }

    return trimRecentJobs(
      parsed
        .filter(isObject)
        .map((item, index): RecentJob | null => {
          if (typeof item.taskId !== "string" || item.taskId.length === 0) {
            return null;
          }

          const fallbackTimestamp = Date.now() - index;
          const conversionId =
            typeof item.conversionId === "string" && item.conversionId.length > 0
              ? item.conversionId
              : undefined;
          const autoDownloadedConversionId =
            typeof item.autoDownloadedConversionId === "string" &&
            item.autoDownloadedConversionId.length > 0 &&
            item.autoDownloadedConversionId === conversionId
              ? item.autoDownloadedConversionId
              : undefined;

          return {
            taskId: item.taskId,
            ...(conversionId ? { conversionId } : {}),
            ...(autoDownloadedConversionId ? { autoDownloadedConversionId } : {}),
            createdAt: readTimestamp(item.createdAt, fallbackTimestamp),
            updatedAt: readTimestamp(item.updatedAt, fallbackTimestamp),
          };
        })
        .filter((job): job is RecentJob => job !== null),
    );
  } catch {
    return [];
  }
}

export function serializeRecentJobs(jobs: RecentJob[]): string {
  return JSON.stringify(trimRecentJobs(jobs));
}
