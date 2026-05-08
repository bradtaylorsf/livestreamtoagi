export function formatDuration(iso: string | null): string {
  if (!iso) return "\u2014";
  const seconds = toSeconds(iso);
  if (seconds === null) return iso;
  const totalSecs = Math.round(seconds);
  const hrs = Math.floor(totalSecs / 3600);
  const mins = Math.floor((totalSecs % 3600) / 60);
  const secs = totalSecs % 60;
  if (hrs > 0) return `${hrs}h ${mins}m`;
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

// Parse either a plain-number-of-seconds string ("1906", "1906.5") or a
// Python timedelta repr ("H:MM:SS[.ffffff]" / "D days, H:MM:SS"). Returns
// null when the input matches neither shape.
function toSeconds(value: string): number | null {
  const trimmed = value.trim();
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
    return parseFloat(trimmed);
  }
  // Python str(timedelta) emits "[D day(s), ]H:MM:SS[.ffffff]"
  const tdMatch =
    /^(?:(\d+)\s*days?,\s*)?(\d{1,3}):(\d{2}):(\d{2}(?:\.\d+)?)$/.exec(trimmed);
  if (tdMatch) {
    const [, days, hours, minutes, sec] = tdMatch;
    return (
      (days ? parseInt(days, 10) * 86400 : 0) +
      parseInt(hours, 10) * 3600 +
      parseInt(minutes, 10) * 60 +
      parseFloat(sec)
    );
  }
  return null;
}
