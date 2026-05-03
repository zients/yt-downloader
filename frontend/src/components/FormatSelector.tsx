import type { FormatPreset, OutputPresets } from "../types";

type FormatSelectorProps = {
  disabled?: boolean;
  onSelect: (preset: FormatPreset) => void;
  presets: OutputPresets;
};

const allowedVideoPresets: FormatPreset[] = [
  { format: "mp4", quality: "1080p" },
  { format: "mp4", quality: "720p" },
];
const allowedAudioPresets: FormatPreset[] = [{ format: "mp3", quality: null }];

function matchesPreset(preset: FormatPreset, allowed: FormatPreset): boolean {
  return (
    preset.format === allowed.format &&
    (preset.quality ?? null) === (allowed.quality ?? null)
  );
}

function findPreset(
  presets: FormatPreset[],
  allowed: FormatPreset,
): FormatPreset | null {
  return presets.find((preset) => matchesPreset(preset, allowed)) ?? null;
}

function isPreset(preset: FormatPreset | null): preset is FormatPreset {
  return preset !== null;
}

export function FormatSelector({
  disabled = false,
  onSelect,
  presets,
}: FormatSelectorProps) {
  const videoPresets = allowedVideoPresets
    .map((allowed) => findPreset(presets.video, allowed))
    .filter(isPreset);
  const audioPresets = allowedAudioPresets
    .map((allowed) => findPreset(presets.audio, allowed))
    .filter(isPreset);

  return (
    <section className="format-selector">
      <div className="format-group">
        <h3>Video</h3>
        <div className="format-grid">
          {videoPresets.map((preset) => (
            <button
              className="format-button video"
              disabled={disabled}
              key={`${preset.format}-${preset.quality ?? "audio"}`}
              onClick={() => onSelect(preset)}
              type="button"
            >
              <span>{preset.format.toUpperCase()}</span>
              {preset.quality ? <small>{preset.quality}</small> : null}
            </button>
          ))}
        </div>
      </div>
      <div className="format-group">
        <h3>Audio</h3>
        <div className="format-grid">
          {audioPresets.map((preset) => (
            <button
              className="format-button audio"
              disabled={disabled}
              key={`${preset.format}-${preset.quality ?? "audio"}`}
              onClick={() => onSelect(preset)}
              type="button"
            >
              <span>{preset.format.toUpperCase()}</span>
              {preset.quality ? <small>{preset.quality}</small> : null}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
