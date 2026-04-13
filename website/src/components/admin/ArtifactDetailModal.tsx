"use client";

import { useEffect } from "react";
import { AGENT_COLORS, STATUS_STYLES, TYPE_ICONS } from "@/lib/artifact-constants";
import type { AgentArtifact } from "@/types/admin";


function getInput(artifact: AgentArtifact): Record<string, unknown> {
  return artifact.tool_input ?? {};
}

function getOutput(artifact: AgentArtifact): Record<string, unknown> | string | null {
  return artifact.tool_output;
}

function str(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded ${STATUS_STYLES[status] ?? "bg-foreground/10 text-foreground/60"}`}
    >
      {status}
    </span>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-foreground/40 mb-1">{label}</p>
      {children}
    </div>
  );
}

function CodeBlock({ children, red }: { children: string; red?: boolean }) {
  return (
    <pre
      className={`text-xs font-mono rounded p-2 overflow-x-auto max-h-64 whitespace-pre-wrap ${
        red
          ? "bg-red-500/5 text-red-400 border border-red-500/20"
          : "bg-surface-light text-foreground/70"
      }`}
    >
      {children}
    </pre>
  );
}

function SocialPostDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const text = str(input.content || input.text || input.message || "");
  const platform = str(input.platform || artifact.metadata?.platform || "");
  return (
    <>
      <Section label="Full Post Text">
        <CodeBlock>{text || str(artifact.tool_output)}</CodeBlock>
      </Section>
      {platform && (
        <Section label="Platform">
          <p className="text-sm text-foreground/70">{platform}</p>
        </Section>
      )}
      <Section label="Character Count">
        <p className="text-sm font-mono text-foreground/70">{text.length}</p>
      </Section>
      <Section label="Status">
        <StatusBadge status={artifact.status} />
        <span className="text-xs text-foreground/40 ml-2">
          (would have been pending human approval)
        </span>
      </Section>
    </>
  );
}

function EmailDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const emailType = str(input.email_type || artifact.metadata?.email_type || "");
  return (
    <>
      <Section label="To">
        <p className="text-sm font-mono text-foreground/70">{str(input.to || input.recipient)}</p>
      </Section>
      <Section label="Subject">
        <p className="text-sm text-foreground/70">{str(input.subject)}</p>
      </Section>
      <Section label="Body">
        <CodeBlock>{str(input.body || input.content)}</CodeBlock>
      </Section>
      {emailType && (
        <Section label="Email Type">
          <p className="text-sm text-foreground/70">{emailType}</p>
        </Section>
      )}
      <Section label="Status">
        <StatusBadge status={artifact.status} />
        <span className="text-xs text-foreground/40 ml-2">(pending approval)</span>
      </Section>
    </>
  );
}

function CodeExecutionDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const output = getOutput(artifact);
  const outputObj = typeof output === "object" && output != null ? output : {};
  const code = str(input.code || input.source);
  const language = str(input.language || "python");
  const stdout = str(outputObj.stdout || outputObj.output || (typeof output === "string" ? output : ""));
  const stderr = str(outputObj.stderr || "");
  const exitCode = outputObj.exit_code ?? outputObj.exitCode;
  const execTime = outputObj.execution_time ?? outputObj.duration;
  const container = outputObj.container ?? artifact.metadata?.container;
  return (
    <>
      <Section label={`Code (${language})`}>
        <pre className={`text-xs font-mono bg-surface-light text-foreground/70 rounded p-2 overflow-x-auto max-h-64 whitespace-pre-wrap language-${language}`}>
          {code}
        </pre>
      </Section>
      {stdout && (
        <Section label="stdout">
          <CodeBlock>{stdout}</CodeBlock>
        </Section>
      )}
      {stderr && (
        <Section label="stderr">
          <CodeBlock red>{stderr}</CodeBlock>
        </Section>
      )}
      {exitCode != null && (
        <Section label="Exit Code">
          <span className={`text-sm font-mono ${exitCode === 0 ? "text-green-400" : "text-red-400"}`}>
            {String(exitCode)}
          </span>
        </Section>
      )}
      {execTime != null && (
        <Section label="Execution Time">
          <p className="text-sm font-mono text-foreground/70">{String(execTime)}</p>
        </Section>
      )}
      {container != null && (
        <Section label="Container Metadata">
          <CodeBlock>{str(container)}</CodeBlock>
        </Section>
      )}
    </>
  );
}

function WebSearchDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const output = getOutput(artifact);
  const query = str(input.query || input.search_query);
  const results = typeof output === "object" && output != null
    ? (Array.isArray(output.results) ? output.results as Record<string, unknown>[] : [])
    : [];
  return (
    <>
      <Section label="Search Query">
        <p className="text-sm font-mono text-foreground/70">{query}</p>
      </Section>
      <Section label={`Results (${results.length})`}>
        {results.length > 0 ? (
          <div className="space-y-2">
            {results.map((r, i) => (
              <div key={i} className="rounded bg-surface-light p-2 text-xs">
                <p className="text-neon-cyan font-medium">{str(r.title)}</p>
                {r.url ? <p className="text-foreground/40 font-mono truncate">{str(r.url)}</p> : null}
                {r.snippet ? <p className="text-foreground/60 mt-1">{str(r.snippet)}</p> : null}
              </div>
            ))}
          </div>
        ) : (
          <CodeBlock>{str(output)}</CodeBlock>
        )}
      </Section>
    </>
  );
}

function PollDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const output = getOutput(artifact);
  const options = Array.isArray(input.options) ? input.options as string[] : [];
  const outputObj = typeof output === "object" && output != null ? output : {};
  return (
    <>
      <Section label="Question">
        <p className="text-sm text-foreground/70">{str(input.question)}</p>
      </Section>
      {options.length > 0 && (
        <Section label="Options">
          <ul className="list-disc list-inside text-sm text-foreground/70">
            {options.map((o, i) => (
              <li key={i}>{str(o)}</li>
            ))}
          </ul>
        </Section>
      )}
      {Object.keys(outputObj).length > 0 && (
        <Section label="Results">
          <CodeBlock>{str(output)}</CodeBlock>
        </Section>
      )}
    </>
  );
}

function MemoryOperationDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const opType = str(input.operation || input.op_type || artifact.metadata?.operation || "");
  return (
    <>
      {opType && (
        <Section label="Operation Type">
          <p className="text-sm font-mono text-foreground/70">{opType}</p>
        </Section>
      )}
      <Section label="Memory Content">
        <CodeBlock>{str(input.content || input.memory || artifact.tool_output)}</CodeBlock>
      </Section>
      <Section label="Agent & Context">
        <p className="text-sm text-foreground/70">
          <span style={{ color: AGENT_COLORS[artifact.agent_id] }}>{artifact.agent_id}</span>
          {input.context ? <span className="text-foreground/40 ml-2">({str(input.context)})</span> : null}
        </p>
      </Section>
    </>
  );
}

function AlphaDispatchDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  return (
    <>
      <Section label="Task Description">
        <CodeBlock>{str(input.task || input.description)}</CodeBlock>
      </Section>
      <Section label="Dispatching Agent">
        <p className="text-sm text-foreground/70">
          <span style={{ color: AGENT_COLORS[artifact.agent_id] }}>{artifact.agent_id}</span>
        </p>
      </Section>
      <Section label="Alpha's Result">
        <CodeBlock>{str(artifact.tool_output)}</CodeBlock>
      </Section>
    </>
  );
}

function MessageDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const content = str(input.content || input.text || input.body || input.message || "");
  const recipient = str(input.to || input.recipient || input.channel || "");
  return (
    <>
      <Section label="Message">
        <div className="rounded bg-surface-light p-3 text-sm text-foreground/80 whitespace-pre-wrap">
          {content || str(artifact.tool_output)}
        </div>
      </Section>
      {recipient && (
        <Section label="Recipient / Channel">
          <p className="text-sm font-mono text-foreground/70">{recipient}</p>
        </Section>
      )}
      <Section label="From">
        <p className="text-sm text-foreground/70">
          <span style={{ color: AGENT_COLORS[artifact.agent_id] }}>{artifact.agent_id}</span>
        </p>
      </Section>
    </>
  );
}

function TilemapDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const output = getOutput(artifact);
  const outputObj = typeof output === "object" && output != null ? output : {};
  const width = input.width ?? outputObj.width ?? input.map_width;
  const height = input.height ?? outputObj.height ?? input.map_height;
  return (
    <>
      {(width != null || height != null) && (
        <Section label="Dimensions">
          <p className="text-sm font-mono text-foreground/70">
            {width != null ? `${width}` : "?"} x {height != null ? `${height}` : "?"}
          </p>
        </Section>
      )}
      <Section label="Tile Data">
        <CodeBlock>{str(input.tiles || input.tile_data || input.data || artifact.tool_input)}</CodeBlock>
      </Section>
      {Object.keys(outputObj).length > 0 && (
        <Section label="Output">
          <CodeBlock>{str(output)}</CodeBlock>
        </Section>
      )}
    </>
  );
}

function SelfModificationDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = getInput(artifact);
  const target = str(input.target || input.file || input.config || "");
  const change = str(input.change || input.modification || input.content || "");
  const reason = str(input.reason || input.justification || "");
  return (
    <>
      {target && (
        <Section label="Target">
          <p className="text-sm font-mono text-foreground/70">{target}</p>
        </Section>
      )}
      <Section label="Change">
        <CodeBlock>{change || str(artifact.tool_input)}</CodeBlock>
      </Section>
      {reason && (
        <Section label="Reason">
          <p className="text-sm text-foreground/70">{reason}</p>
        </Section>
      )}
      <Section label="Result">
        <CodeBlock>{str(artifact.tool_output)}</CodeBlock>
      </Section>
    </>
  );
}

function GenericDetail({ artifact }: { artifact: AgentArtifact }) {
  const input = artifact.tool_input ?? {};
  const output = artifact.tool_output;

  // Try to extract common meaningful fields
  const contentField = input.content ?? input.text ?? input.description ?? input.result;
  const hasContent = typeof contentField === "string" && contentField.length > 0;

  return (
    <>
      {hasContent && (
        <Section label="Content">
          <div className="rounded bg-surface-light p-3 text-sm text-foreground/80 whitespace-pre-wrap">
            {contentField as string}
          </div>
        </Section>
      )}
      <Section label={hasContent ? "Full Input" : "Input"}>
        <pre className="text-xs font-mono bg-surface-light text-foreground/70 rounded p-2 overflow-x-auto max-h-64 whitespace-pre-wrap">
          {JSON.stringify(input, null, 2)}
        </pre>
      </Section>
      <Section label="Output">
        <pre className="text-xs font-mono bg-surface-light text-foreground/70 rounded p-2 overflow-x-auto max-h-64 whitespace-pre-wrap">
          {typeof output === "string" ? output : JSON.stringify(output, null, 2)}
        </pre>
      </Section>
    </>
  );
}

const TYPE_RENDERERS: Record<string, React.ComponentType<{ artifact: AgentArtifact }>> = {
  social_post: SocialPostDetail,
  email: EmailDetail,
  code_execution: CodeExecutionDetail,
  code: CodeExecutionDetail,
  web_search: WebSearchDetail,
  search: WebSearchDetail,
  poll: PollDetail,
  memory_operation: MemoryOperationDetail,
  alpha_dispatch: AlphaDispatchDetail,
  message: MessageDetail,
  tilemap: TilemapDetail,
  self_modification: SelfModificationDetail,
};

interface Props {
  artifact: AgentArtifact;
  onClose: () => void;
}

export default function ArtifactDetailModal({ artifact, onClose }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const Renderer = TYPE_RENDERERS[artifact.artifact_type] ?? GenericDetail;
  const icon = TYPE_ICONS[artifact.artifact_type] ?? "◇";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-16 px-4 overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-3xl rounded-lg border border-border bg-surface shadow-xl mb-16">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-lg">{icon}</span>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-foreground">
                  {artifact.artifact_type}
                </span>
                <span className="text-xs font-mono text-foreground/40">
                  {artifact.tool_name}
                </span>
                <StatusBadge status={artifact.status} />
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  className="text-xs font-medium"
                  style={{ color: AGENT_COLORS[artifact.agent_id] ?? "#888" }}
                >
                  {artifact.agent_id}
                </span>
                <span className="text-xs text-foreground/30">
                  {new Date(artifact.created_at).toLocaleString()}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-foreground/40 hover:text-foreground hover:bg-surface-light transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-4 space-y-4">
          <Renderer artifact={artifact} />

          {/* Metadata (always show if present) */}
          {artifact.metadata && Object.keys(artifact.metadata).length > 0 && (
            <Section label="Metadata">
              <CodeBlock>{JSON.stringify(artifact.metadata, null, 2)}</CodeBlock>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
