interface WorldScreenshot {
  id: string;
  date: string;
  description: string;
}

// TODO: Replace with actual screenshots once available
const PLACEHOLDER_SCREENSHOTS: WorldScreenshot[] = [
  {
    id: "1",
    date: "2026-04-01",
    description: "Day 1 — The original office layout with default tileset",
  },
  {
    id: "2",
    date: "2026-04-04",
    description: "After Aurora's color renovation — warm tones throughout",
  },
  {
    id: "3",
    date: "2026-04-07",
    description: "Current state — office, break room, and server room",
  },
];

export default function WorldGallery() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {PLACEHOLDER_SCREENSHOTS.map((screenshot) => (
        <div
          key={screenshot.id}
          className="rounded border border-border bg-surface overflow-hidden"
        >
          {/* Placeholder for actual screenshot images */}
          <div className="aspect-video bg-surface-light flex items-center justify-center">
            <span className="text-xs text-foreground/30 font-pixel">
              Screenshot
            </span>
          </div>
          <div className="p-3">
            <time className="text-xs text-foreground/40">{screenshot.date}</time>
            <p className="text-xs text-foreground/60 mt-1">
              {screenshot.description}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
