// Renders a human-readable label for a conversation row based on its topics.
// Falls back to an em-dash when no detected topic is present so that callers
// don't accidentally surface status fields (e.g. "idle") in the topic column.
export function conversationTopicLabel(
  topics: string[] | null | undefined,
): string {
  const first = topics?.[0];
  if (typeof first === "string" && first.trim().length > 0) {
    return first;
  }
  return "—";
}
