import {
  flattenAvailablePresets,
  getDefaultFormatPreset,
  getPresetKey,
} from "../src/formatPresets";
import type { FormatPreset, OutputPresets } from "../src/types";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

function assertEqual<T>(actual: T, expected: T, message: string) {
  if (actual !== expected) {
    throw new Error(
      `${message}: expected ${String(expected)}, got ${String(actual)}`,
    );
  }
}

function assertPresetEqual(
  actual: FormatPreset | null,
  expected: FormatPreset,
  message: string,
) {
  assert(actual !== null, `${message}: expected preset, got null`);
  assertEqual(actual.format, expected.format, `${message} format`);
  assertEqual(
    actual.quality ?? null,
    expected.quality ?? null,
    `${message} quality`,
  );
}

function testFlattenAvailablePresetsPreservesAudioThenVideoOrder() {
  const presets: OutputPresets = {
    audio: [
      { format: "aac", quality: null },
      { format: "mp3", quality: null },
    ],
    video: [
      { format: "mp4", quality: "720p" },
      { format: "webm", quality: "1080p" },
    ],
  };

  const flattened = flattenAvailablePresets(presets);

  assertEqual(flattened.length, 4, "returns every available preset");
  assertEqual(getPresetKey(flattened[0]), "aac-audio", "first audio key");
  assertEqual(getPresetKey(flattened[1]), "mp3-audio", "second audio key");
  assertEqual(getPresetKey(flattened[2]), "mp4-720p", "first video key");
  assertEqual(getPresetKey(flattened[3]), "webm-1080p", "second video key");
}

function testGetDefaultFormatPresetPrefersMp3Audio() {
  const defaultPreset = getDefaultFormatPreset({
    audio: [
      { format: "aac", quality: null },
      { format: "mp3", quality: null },
    ],
    video: [{ format: "mp4", quality: "1080p" }],
  });

  assertPresetEqual(
    defaultPreset,
    { format: "mp3", quality: null },
    "prefers mp3 audio",
  );
}

function testGetDefaultFormatPresetFallsBackToFirstAudio() {
  const defaultPreset = getDefaultFormatPreset({
    audio: [{ format: "aac", quality: null }],
    video: [{ format: "mp4", quality: "720p" }],
  });

  assertPresetEqual(
    defaultPreset,
    { format: "aac", quality: null },
    "falls back to first audio preset",
  );
}

function testGetDefaultFormatPresetFallsBackToFirstVideo() {
  const defaultPreset = getDefaultFormatPreset({
    audio: [],
    video: [{ format: "mp4", quality: "720p" }],
  });

  assertPresetEqual(
    defaultPreset,
    { format: "mp4", quality: "720p" },
    "falls back to first video preset",
  );
}

function testGetDefaultFormatPresetReturnsNullForNoPresets() {
  const defaultPreset = getDefaultFormatPreset({ audio: [], video: [] });

  assertEqual(defaultPreset, null, "returns null without available presets");
}

testFlattenAvailablePresetsPreservesAudioThenVideoOrder();
testGetDefaultFormatPresetPrefersMp3Audio();
testGetDefaultFormatPresetFallsBackToFirstAudio();
testGetDefaultFormatPresetFallsBackToFirstVideo();
testGetDefaultFormatPresetReturnsNullForNoPresets();

console.log("formatPresets tests passed");
