/**
 * Shared constants for artifact display components.
 *
 * Canonical source for TYPE_ICONS, AGENT_COLORS (hex), and
 * artifact STATUS_STYLES used across ArtifactCard, ArtifactDetailModal,
 * ArtifactDetail, and the artifacts page.
 */

/** Emoji icons for each artifact type. */
export const TYPE_ICONS: Record<string, string> = {
  social_post: "📱",
  email: "✉",
  code_execution: "⌨",
  code: "⌨",
  web_search: "🔍",
  search: "🔍",
  web_fetch: "🌐",
  tilemap: "🗺",
  poll: "📊",
  memory_operation: "🧠",
  alpha_dispatch: "🐺",
  self_modification: "🔧",
  message: "💬",
  file_write: "📄",
};

/** Hex colors per agent — for use with inline style={{ color }}. */
export const AGENT_COLORS: Record<string, string> = {
  vera: "#9b59b6",
  rex: "#e74c3c",
  aurora: "#f1c40f",
  pixel: "#3498db",
  fork: "#2ecc71",
  sentinel: "#e67e22",
  grok: "#1abc9c",
  overseer: "#95a5a6",
  alpha: "#8e44ad",
};

/** Tailwind classes for artifact status badges. */
export const STATUS_STYLES: Record<string, string> = {
  draft: "bg-yellow-500/10 text-yellow-400",
  executed: "bg-green-500/10 text-green-400",
  success: "bg-green-500/10 text-green-400",
  failed: "bg-red-500/10 text-red-400",
  error: "bg-red-500/10 text-red-400",
  pending_approval: "bg-blue-500/10 text-blue-400",
  pending: "bg-yellow-500/10 text-yellow-400",
};
