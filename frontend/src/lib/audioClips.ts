// Helpers for slicing the temporary in-browser meeting recording. Nothing here is persisted.

export const SAMPLE_RATE = 16_000;
export const MIN_SAMPLE_SECONDS = 8; // Keep in sync with MIN_SAMPLE_SECONDS in backend/app/voice.py.
export const MAX_SAMPLE_SECONDS = 60;
const CLIP_PADDING_MS = 150;

type TimedTurn = { speaker: "advisor" | "customer"; startTimeMs: number; endTimeMs: number };

export async function decodeRecording(recording: Blob): Promise<AudioBuffer> {
  const context = new AudioContext();
  try {
    return await context.decodeAudioData(await recording.arrayBuffer());
  } finally {
    void context.close();
  }
}

function resampleMono(buffer: AudioBuffer, startMs: number, endMs: number): Float32Array {
  const source = buffer.getChannelData(0);
  const from = Math.max(0, Math.floor((startMs / 1000) * buffer.sampleRate));
  const to = Math.min(source.length, Math.ceil((endMs / 1000) * buffer.sampleRate));
  const length = Math.max(0, Math.floor(((to - from) / buffer.sampleRate) * SAMPLE_RATE));
  const output = new Float32Array(length);
  const step = buffer.sampleRate / SAMPLE_RATE;
  for (let index = 0; index < length; index += 1) {
    const position = from + index * step;
    const base = Math.floor(position);
    const next = Math.min(base + 1, source.length - 1);
    const fraction = position - base;
    output[index] = source[base] * (1 - fraction) + source[next] * fraction;
  }
  return output;
}

export function encodeWav(samples: Float32Array): Blob {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const writeText = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeText(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return new Blob([view], { type: "audio/wav" });
}

export function sliceClip(buffer: AudioBuffer, startMs: number, endMs: number): Blob {
  return encodeWav(resampleMono(buffer, startMs - CLIP_PADDING_MS, endMs + CLIP_PADDING_MS));
}

/**
 * Adviser-only voice sample: the longest adviser turns first, up to MAX_SAMPLE_SECONDS,
 * joined in meeting order. Customer speech is never included.
 */
export function buildAdviserSample(buffer: AudioBuffer, turns: TimedTurn[]): Blob | null {
  const advisorTurns = turns
    .filter((turn) => turn.speaker === "advisor" && turn.endTimeMs > turn.startTimeMs)
    .sort((a, b) => b.endTimeMs - b.startTimeMs - (a.endTimeMs - a.startTimeMs));
  const chosen: TimedTurn[] = [];
  let totalMs = 0;
  for (const turn of advisorTurns) {
    const duration = turn.endTimeMs - turn.startTimeMs;
    if (totalMs + duration > MAX_SAMPLE_SECONDS * 1000) continue;
    chosen.push(turn);
    totalMs += duration;
  }
  if (totalMs < MIN_SAMPLE_SECONDS * 1000) return null;
  const parts = chosen
    .sort((a, b) => a.startTimeMs - b.startTimeMs)
    .map((turn) => resampleMono(buffer, turn.startTimeMs, turn.endTimeMs));
  const samples = new Float32Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    samples.set(part, offset);
    offset += part.length;
  }
  return encodeWav(samples);
}
