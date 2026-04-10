"use client";

interface PlaybackControlsProps {
  currentTurn: number;
  totalTurns: number;
  isPlaying: boolean;
  speed: number;
  onPlayPause: () => void;
  onSpeedChange: (speed: number) => void;
  onTurnChange: (turn: number) => void;
}

const SPEED_OPTIONS = [1, 2, 4];

export default function PlaybackControls({
  currentTurn,
  totalTurns,
  isPlaying,
  speed,
  onPlayPause,
  onSpeedChange,
  onTurnChange,
}: PlaybackControlsProps) {
  return (
    <div className="flex items-center gap-4 rounded border border-border bg-surface p-3">
      {/* Play/Pause */}
      <button
        onClick={onPlayPause}
        className="flex h-8 w-8 items-center justify-center rounded bg-neon-cyan/20 text-neon-cyan hover:bg-neon-cyan/30 transition-colors"
        aria-label={isPlaying ? "Pause" : "Play"}
      >
        {isPlaying ? (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
            <rect x="2" y="1" width="3" height="12" />
            <rect x="9" y="1" width="3" height="12" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
            <path d="M3 1l10 6-10 6V1z" />
          </svg>
        )}
      </button>

      {/* Turn slider */}
      <div className="flex-1 flex items-center gap-2">
        <span className="text-xs text-foreground/50 w-16 text-right">
          Turn {currentTurn}/{totalTurns}
        </span>
        <input
          type="range"
          min={1}
          max={totalTurns}
          value={currentTurn}
          onChange={(e) => onTurnChange(Number(e.target.value))}
          className="flex-1 accent-neon-cyan"
          aria-label="Jump to turn"
        />
      </div>

      {/* Speed selector */}
      <div className="flex items-center gap-1">
        {SPEED_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSpeedChange(s)}
            className={`rounded px-2 py-1 text-xs transition-colors ${
              speed === s
                ? "bg-neon-cyan/20 text-neon-cyan"
                : "text-foreground/50 hover:text-foreground"
            }`}
            aria-label={`${s}x speed`}
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
}
