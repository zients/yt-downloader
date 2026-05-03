import { useId } from "react";

import {
  findMatchingPreset,
  flattenAvailablePresets,
  getPresetKey,
  getPresetLabel,
} from "../formatPresets";
import type { FormatPreset, OutputPresets } from "../types";

type FormatSelectorProps = {
  disabled?: boolean;
  onChange: (preset: FormatPreset | null) => void;
  presets: OutputPresets;
  selectedPreset: FormatPreset | null;
};

export function FormatSelector({
  disabled = false,
  onChange,
  presets,
  selectedPreset,
}: FormatSelectorProps) {
  const selectId = useId();
  const availablePresets = flattenAvailablePresets(presets);
  const selectedAvailablePreset = findMatchingPreset(
    availablePresets,
    selectedPreset,
  );
  const selectedKey = selectedAvailablePreset
    ? getPresetKey(selectedAvailablePreset)
    : "";

  function handleChange(value: string) {
    onChange(
      availablePresets.find((preset) => getPresetKey(preset) === value) ??
        null,
    );
  }

  return (
    <div className="format-selector">
      <label htmlFor={selectId}>Format</label>
      <select
        disabled={disabled || availablePresets.length === 0}
        id={selectId}
        onChange={(event) => handleChange(event.target.value)}
        value={selectedKey}
      >
        {availablePresets.length === 0 ? (
          <option value="">No formats available</option>
        ) : null}
        {availablePresets.map((preset) => (
          <option key={getPresetKey(preset)} value={getPresetKey(preset)}>
            {getPresetLabel(preset)}
          </option>
        ))}
      </select>
    </div>
  );
}
