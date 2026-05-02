export type SourceStatus =
  | "source_pending"
  | "source_processing"
  | "source_ready"
  | "failed";

export type ConversionStatus =
  | "conversion_pending"
  | "conversion_processing"
  | "conversion_ready"
  | "failed";

export type VideoFormat = "mp4" | "webm" | "mkv" | "avi" | "mov";
export type AudioFormat = "mp3" | "wav" | "flac" | "aac" | "ogg" | "m4a";
export type OutputFormat = VideoFormat | AudioFormat;
export type VideoQuality = "1080p" | "720p" | "480p";

export type FormatPreset = {
  format: OutputFormat;
  quality?: VideoQuality | null;
};

export type OutputPresets = {
  video: FormatPreset[];
  audio: FormatPreset[];
};

export type TaskCreateRequest = {
  url: string;
};

export type TaskCreateResponse = {
  task_id: string;
  status: "source_pending";
};

export type TaskStatusResponse = {
  task_id: string;
  status: SourceStatus;
  title?: string | null;
  thumbnail?: string | null;
  progress?: number | null;
  message?: string | null;
  output_presets?: OutputPresets | null;
  error?: string | null;
};

export type ConversionCreateRequest = {
  format: OutputFormat;
  quality?: VideoQuality | null;
};

export type ConversionCreateResponse = {
  conversion_id: string;
  task_id: string;
  status: "conversion_pending";
};

export type ConversionStatusResponse = {
  conversion_id: string;
  task_id: string;
  status: ConversionStatus;
  progress?: number | null;
  message?: string | null;
  download_url?: string | null;
  error?: string | null;
};
