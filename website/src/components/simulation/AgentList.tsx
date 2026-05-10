import Link from "next/link";

interface AgentListProps {
  agents: string[];
  linkPrefix?: string;
  title?: string;
}

export default function AgentList({
  agents,
  linkPrefix,
  title = "Agents Participated",
}: AgentListProps) {
  if (agents.length === 0) return null;

  return (
    <div>
      <h2 className="text-sm font-medium text-foreground/70 mb-2">
        {title}
      </h2>
      <div className="flex flex-wrap gap-2">
        {agents.map((agent) =>
          linkPrefix ? (
            <Link
              key={agent}
              href={`${linkPrefix}/${agent}`}
              className="rounded border border-border bg-surface-light px-2 py-1 text-xs text-foreground/70 hover:text-neon-cyan transition-colors"
            >
              {agent}
            </Link>
          ) : (
            <span
              key={agent}
              className="rounded border border-border bg-surface-light px-2 py-1 text-xs text-foreground/70"
            >
              {agent}
            </span>
          ),
        )}
      </div>
    </div>
  );
}
