import type { FormatPreset, OutputPresets } from "./types";

export function getPresetKey(preset: FormatPreset): string {
  return `${preset.format}-${preset.quality ?? "audio"}`;
}

export function getPresetLabel(preset: FormatPreset): string {
  const format = preset.format.toUpperCase();

  return preset.quality ? `${format} ${preset.quality}` : `${format} audio`;
}

export function flattenAvailablePresets(
  presets: OutputPresets | null | undefined,
): FormatPreset[] {
  if (!presets) {
    return [];
  }

  return [...presets.audio, ...presets.video];
}

export function presetsMatch(
  first: FormatPreset | null | undefined,
  second: FormatPreset | null | undefined,
): boolean {
  return (
    Boolean(first) &&
    Boolean(second) &&
    first?.format === second?.format &&
    (first?.quality ?? null) === (second?.quality ?? null)
  );
}

export function findMatchingPreset(
  presets: FormatPreset[],
  selectedPreset: FormatPreset | null,
): FormatPreset | null {
  return (
    presets.find((preset) => presetsMatch(preset, selectedPreset)) ?? null
  );
}

export function getDefaultFormatPreset(
  presets: OutputPresets | null | undefined,
): FormatPreset | null {
  if (!presets) {
    return null;
  }

  const mp3Preset =
    presets.audio.find(
      (preset) =>
        preset.format === "mp3" && (preset.quality ?? null) === null,
    ) ?? null;

  return mp3Preset ?? presets.audio[0] ?? presets.video[0] ?? null;
}
