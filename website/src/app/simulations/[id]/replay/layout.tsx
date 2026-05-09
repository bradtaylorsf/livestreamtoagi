import type { ReactNode } from "react";

export const metadata = {
  title: "Replay",
  robots: { index: false, follow: false },
};

/**
 * Replay layout — full-bleed black backdrop, non-indexable. The route is
 * captured by Playwright and turned into an MP4 by the render pipeline,
 * so any chrome added here would bleed into the final video.
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
