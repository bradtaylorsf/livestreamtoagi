interface ToolEntry {
  tool_name: string;
  count: number;
  success_rate?: number;
  statuses?: Record<string, number>;
}

const EXPECTED_KEYS = new Set([
  "by_tool",
  "total_invocations",
  "success_rate",
  "tools_never_used",
  "tools_used",
  "by_agent",
  "by_day",
]);

export default function ToolUsageSection({
  data,
}: {
  data: Record<string, unknown>;
}) {
  // Warn when backend sends keys we don't expect
  if (typeof window !== "undefined") {
    const unexpected = Object.keys(data).filter((k) => !EXPECTED_KEYS.has(k));
    if (unexpected.length > 0) {
      console.warn(
        `[ToolUsageSection] Unexpected data keys from backend: ${unexpected.join(", ")}`,
      );
    }
  }

  // Backend sends by_tool dict, transform to array
  const byTool =
    (data.by_tool as
      | Record<
          string,
          {
            count: number;
            success_rate?: number;
            statuses?: Record<string, number>;
          }
        >
      | undefined) ?? {};
  const tools: ToolEntry[] = Object.entries(byTool)
    .map(([name, info]) => ({
      tool_name: name,
      count: info.count ?? 0,
      success_rate: info.success_rate,
      statuses: info.statuses,
    }))
    .sort((a, b) => b.count - a.count);

  const totalInvocations =
    (data.total_invocations as number | undefined) ?? 0;
  const overallSuccessRate = data.success_rate as number | undefined;
  const toolsNeverUsed =
    (data.tools_never_used as string[] | undefined) ?? [];
  const toolsUsed = (data.tools_used as string[] | undefined) ?? [];
  const byDay =
    (data.by_day as Record<string, Record<string, number>> | undefined) ?? {};
  const dailyEntries = Object.entries(byDay).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  if (tools.length === 0 && totalInvocations === 0) {
    return (
      <p className="text-sm text-foreground/50">
        No tool invocations recorded for this simulation.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded border border-border bg-surface-light p-3">
          <div className="text-xs text-foreground/50 mb-1">
            Total Invocations
          </div>
          <div className="font-mono text-sm text-foreground">
            {totalInvocations}
          </div>
        </div>
        <div className="rounded border border-border bg-surface-light p-3">
          <div className="text-xs text-foreground/50 mb-1">Unique Tools</div>
          <div className="font-mono text-sm text-foreground">
            {toolsUsed.length > 0 ? toolsUsed.length : tools.length}
          </div>
        </div>
        {overallSuccessRate != null && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">Success Rate</div>
            <div className="font-mono text-sm text-foreground">
              {overallSuccessRate.toFixed(1)}%
            </div>
          </div>
        )}
        {dailyEntries.length > 0 && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">Active Days</div>
            <div className="font-mono text-sm text-foreground">
              {dailyEntries.length}
            </div>
          </div>
        )}
      </div>

      {/* Tool table */}
      {tools.length > 0 && (
        <div className="rounded-lg border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th scope="col" className="px-4 py-2 font-medium">
                  Tool
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Count
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Success Rate
                </th>
              </tr>
            </thead>
            <tbody>
              {tools.map((tool, idx) => (
                <tr
                  key={idx}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-xs">
                    {tool.tool_name}
                  </td>
                  <td className="px-4 py-2 font-mono text-right">
                    {tool.count}
                  </td>
                  <td className="px-4 py-2 font-mono text-right">
                    {tool.success_rate != null
                      ? `${tool.success_rate.toFixed(1)}%`
                      : "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Daily tool usage */}
      {dailyEntries.length > 0 && (
        <div>
          <div className="text-xs text-foreground/50 mb-2 font-medium">
            Tool Usage by Day
          </div>
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th scope="col" className="px-4 py-2 font-medium">Day</th>
                  <th scope="col" className="px-4 py-2 font-medium">Tools</th>
                </tr>
              </thead>
              <tbody>
                {dailyEntries.map(([day, dayTools]) => (
                  <tr
                    key={day}
                    className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                  >
                    <td className="px-4 py-2 font-mono text-xs">{day}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(dayTools).map(([tool, count]) => (
                          <span
                            key={tool}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-surface-light text-foreground/60"
                          >
                            {tool}: {count}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Agent tool usage */}
      {data.by_agent != null &&
        Object.keys(data.by_agent as Record<string, unknown>).length > 0 && (
          <div>
            <div className="text-xs text-foreground/50 mb-2 font-medium">
              Agent Tool Usage
            </div>
            <div className="rounded-lg border border-border bg-surface overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-foreground/50">
                    <th scope="col" className="px-4 py-2 font-medium">
                      Agent
                    </th>
                    <th scope="col" className="px-4 py-2 font-medium">
                      Tools Used
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(
                    data.by_agent as Record<string, Record<string, number>>,
                  ).map(([agent, agentTools]) => (
                    <tr
                      key={agent}
                      className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                    >
                      <td className="px-4 py-2 font-mono text-xs">{agent}</td>
                      <td className="px-4 py-2">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(agentTools).map(([tool, count]) => (
                            <span
                              key={tool}
                              className="text-[10px] px-1.5 py-0.5 rounded bg-surface-light text-foreground/60"
                            >
                              {tool}: {count}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

      {/* Tools never used */}
      {toolsNeverUsed.length > 0 && (
        <div>
          <div className="text-xs text-foreground/40 mb-2">
            Available tools not used in this simulation:
          </div>
          <div className="flex flex-wrap gap-1.5">
            {toolsNeverUsed.map((tool) => (
              <span
                key={tool}
                className="text-[10px] px-1.5 py-0.5 rounded bg-surface-light text-foreground/30"
              >
                {tool}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
