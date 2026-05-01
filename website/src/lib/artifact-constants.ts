/**
 * Shared constants for artifact display components.
 *
 * TYPE_ICONS, AGENT_COLORS (re-exported from agent-data), and
 * artifact STATUS_STYLES used across ArtifactCard, ArtifactDetailModal,
 * ArtifactDetail, and the artifacts page.
 */

import { AGENT_COLORS } from "@/lib/agent-data";

export { AGENT_COLORS };

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
