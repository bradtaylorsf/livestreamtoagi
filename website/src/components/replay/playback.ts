import type { ReplayCue } from "@/lib/api";

export interface BubblePlan {
  agent_id: string;
  text: string;
  /** Milliseconds from playback start when the bubble appears. */
  start_ms: number;
  /** Milliseconds from playback start when the bubble disappears. */
  end_ms: number;
}

export interface ReplayPlan {
  bubbles: BubblePlan[];
  /** Milliseconds from playback start when ``window.__replayDone`` flips. */
  done_at_ms: number;
}

const PER_CHAR_MS = 60;
const PER_CUE_BUFFER_MS = 500;
const TRAILING_BUFFER_MS = 1000;
const MIN_PLAYBACK_MS = 1000;

function estimateDurationMs(text: string): number {
  return text.length * PER_CHAR_MS + PER_CUE_BUFFER_MS;
}

/**
 * Build a deterministic playback plan for the headless replay capture.
 *
 * Each cue becomes a bubble that appears at ``cue.start_seconds`` and stays
 * visible for either an estimated TTS duration (~60ms/char + 0.5s) or until
 * the next cue starts, whichever is shorter. The plan also computes the
 * point at which the page should set ``window.__replayDone = true`` —
 * that's the last bubble's end + 1s, with a hard floor of 1s.
 */
export function planReplay(cues: ReplayCue[]): ReplayPlan {
  if (cues.length === 0) {
    return { bubbles: [], done_at_ms: MIN_PLAYBACK_MS };
  }

  const sorted = [...cues].sort((a, b) => a.start_seconds - b.start_seconds);
  const bubbles: BubblePlan[] = sorted.map((cue, idx) => {
    const start_ms = Math.max(0, Math.round(cue.start_seconds * 1000));
    const next_start_ms =
      idx + 1 < sorted.length
        ? Math.round(sorted[idx + 1].start_seconds * 1000)
        : Number.POSITIVE_INFINITY;
    const estimated_end_ms = start_ms + estimateDurationMs(cue.text);
    const end_ms = Math.min(estimated_end_ms, next_start_ms);
    return {
      agent_id: cue.agent_id,
      text: cue.text,
      start_ms,
      end_ms,
    };
  });

  const last_end = bubbles[bubbles.length - 1].end_ms;
  const done_at_ms = Math.max(MIN_PLAYBACK_MS, last_end + TRAILING_BUFFER_MS);
  return { bubbles, done_at_ms };
}

export const __PLAYBACK_TUNABLES = {
  PER_CHAR_MS,
  PER_CUE_BUFFER_MS,
  TRAILING_BUFFER_MS,
  MIN_PLAYBACK_MS,
};
