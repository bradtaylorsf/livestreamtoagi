import type { ReactNode } from "react";

export const metadata = {
  title: "Replay",
  robots: { index: false, follow: false },
};

/**
 * The replay route is captured by Playwright and turned into an MP4. The
 * outer ``app/simulations/[id]/layout.tsx`` already wraps children in a
 * ``SimulationProvider``; this layout exists only so we can mark the page
 * non-indexable and add a full-bleed black backdrop without touching the
 * shared simulation chrome.
 */
export default function ReplayLayout({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        position: "relative",
        background: "#000",
        minHeight: "100vh",
      }}
    >
      {children}
    </div>
  );
}
