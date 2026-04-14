export function formatDuration(iso: string | null): string {
  if (!iso) return "\u2014";
  const seconds = parseFloat(iso);
  if (!isNaN(seconds)) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    if (mins >= 60) {
      const hrs = Math.floor(mins / 60);
      return `${hrs}h ${mins % 60}m`;
    }
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  }
  return iso;
}
