import type { FormatPreset, OutputFormat, VideoQuality } from "./types";

export const RECENT_JOBS_LIMIT = 5;
export const RECENT_JOBS_STORAGE_KEY = "yt-downloader:recent-jobs";

const AUDIO_FORMATS = new Set(["mp3", "wav", "flac", "aac", "ogg", "m4a"]);
const VIDEO_FORMATS = new Set(["mp4", "webm", "mkv", "avi", "mov"]);
const VIDEO_QUALITIES = new Set(["1080p", "720p", "480p"]);

export type RecentJob = {
  taskId: string;
  conversionId?: string;
  conversionPreset?: FormatPreset;
  autoDownloadedConversionId?: string;
  createdAt: number;
  updatedAt: number;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readTimestamp(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function readConversionPreset(value: unknown): FormatPreset | undefined {
  if (!isObject(value) || typeof value.format !== "string") {
    return undefined;
  }

  if (AUDIO_FORMATS.has(value.format)) {
    return value.quality === undefined || value.quality === null
      ? { format: value.format as OutputFormat }
      : undefined;
  }

  if (
    VIDEO_FORMATS.has(value.format) &&
    typeof value.quality === "string" &&
    VIDEO_QUALITIES.has(value.quality)
  ) {
    return {
      format: value.format as OutputFormat,
      quality: value.quality as VideoQuality,
    };
  }

  return undefined;
}

function normalizeConversionPreset(preset: FormatPreset): FormatPreset {
  if (AUDIO_FORMATS.has(preset.format)) {
    return { format: preset.format };
  }

  return preset.quality
    ? { format: preset.format, quality: preset.quality }
    : { format: preset.format };
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
    ...(existingJob?.conversionId && existingJob.conversionPreset
      ? {
          conversionId: existingJob.conversionId,
          conversionPreset: existingJob.conversionPreset,
        }
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
  conversionPreset: FormatPreset,
  timestamp = Date.now(),
): RecentJob[] {
  return jobs.map((job) =>
    job.taskId === taskId
      ? {
          ...job,
          conversionId,
          conversionPreset: normalizeConversionPreset(conversionPreset),
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
          const conversionPreset = readConversionPreset(item.conversionPreset);
          const hydratedConversionId = conversionPreset ? conversionId : undefined;
          const autoDownloadedConversionId =
            typeof item.autoDownloadedConversionId === "string" &&
            item.autoDownloadedConversionId.length > 0 &&
            item.autoDownloadedConversionId === hydratedConversionId
              ? item.autoDownloadedConversionId
              : undefined;

          return {
            taskId: item.taskId,
            ...(hydratedConversionId
              ? { conversionId: hydratedConversionId, conversionPreset }
              : {}),
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
