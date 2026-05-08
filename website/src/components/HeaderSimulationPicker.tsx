"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  getSimulation,
  getSimulations,
  type PublicSimulation,
} from "@/lib/api";
import { useSimulation } from "@/lib/SimulationContext";
import { sortSimulations } from "@/components/SimulationPicker";

const AGGREGATE_LABEL = "Aggregate (no simulation selected)";

export function filterSimulations(
  sims: PublicSimulation[],
  query: string,
): PublicSimulation[] {
  const q = query.trim().toLowerCase();
  if (!q) return sims;
  return sims.filter((s) => s.name.toLowerCase().includes(q));
}

export function buildPickerLabel(
  activeId: string | null,
  active: PublicSimulation | null,
): string {
  if (!activeId) return AGGREGATE_LABEL;
  if (active) return `${active.name} · ${active.status}`;
  return activeId;
}

export default function HeaderSimulationPicker() {
  const { simulationId, setSimulationId } = useSimulation();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [simulations, setSimulations] = useState<PublicSimulation[]>([]);
  const [activeDetail, setActiveDetail] = useState<PublicSimulation | null>(
    null,
  );
  const [focusIndex, setFocusIndex] = useState<number>(-1);

  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();

  // Load most-recent simulations once on mount.
  useEffect(() => {
    let cancelled = false;
    getSimulations({ limit: 10 })
      .then((data) => {
        if (cancelled) return;
        setSimulations(sortSimulations(data.items));
      })
      .catch(() => {
        // Non-fatal — picker still works without recents.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // When the active simulation isn't in the recents list, fetch its detail
  // so we can show its name + status in the trigger.
  useEffect(() => {
    if (!simulationId) {
      setActiveDetail(null);
      return;
    }
    const inList = simulations.find((s) => s.id === simulationId);
    if (inList) {
      setActiveDetail(inList);
      return;
    }
    let cancelled = false;
    getSimulation(simulationId)
      .then((sim) => {
        if (cancelled) return;
        setActiveDetail(sim);
      })
      .catch(() => {
        if (cancelled) return;
        setActiveDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId, simulations]);

  const filtered = useMemo(
    () => filterSimulations(simulations, query),
    [simulations, query],
  );

  const closePopover = useCallback(() => {
    setOpen(false);
    setQuery("");
    setFocusIndex(-1);
  }, []);

  const openPopover = useCallback(() => {
    setOpen(true);
    setFocusIndex(-1);
  }, []);

  // Click-outside to close.
  useEffect(() => {
    if (!open) return;
    function onMouseDown(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        closePopover();
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open, closePopover]);

  // Global "/" keybinding to open the popover.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "/") return;
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (
          tag === "INPUT" ||
          tag === "TEXTAREA" ||
          tag === "SELECT" ||
          target.isContentEditable
        ) {
          return;
        }
      }
      e.preventDefault();
      openPopover();
      // Focus search after the popover renders.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openPopover]);

  // Focus the search input when popover opens.
  useEffect(() => {
    if (open) {
      // Defer to next tick to ensure the input is mounted.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // Items: "Aggregate" pseudo-row + filtered sims.
  const optionCount = 1 + filtered.length;

  function selectIndex(index: number) {
    if (index === 0) {
      // Aggregate: clear context and stay on the current page.
      setSimulationId(null);
      closePopover();
      return;
    }
    const sim = filtered[index - 1];
    if (!sim) return;
    setSimulationId(sim.id);
    router.push(`/simulations/${sim.id}`);
    closePopover();
  }

  function onListKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusIndex((idx) => (idx + 1 >= optionCount ? 0 : idx + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusIndex((idx) =>
        idx <= 0 ? Math.max(optionCount - 1, 0) : idx - 1,
      );
    } else if (e.key === "Enter") {
      if (focusIndex >= 0) {
        e.preventDefault();
        selectIndex(focusIndex);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      closePopover();
      buttonRef.current?.focus();
    }
  }

  const triggerLabel = buildPickerLabel(simulationId, activeDetail);
  const activeOptionId =
    focusIndex >= 0 ? `${listboxId}-opt-${focusIndex}` : undefined;

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => (open ? closePopover() : openPopover())}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        data-testid="header-simulation-picker"
        title={triggerLabel}
        className="rounded border border-border bg-surface-light px-3 py-1.5 text-xs text-foreground/80 hover:bg-surface hover:text-foreground transition-colors max-w-[16rem] truncate"
      >
        {triggerLabel}
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-72 rounded border border-border bg-surface shadow-lg z-50"
          onKeyDown={onListKeyDown}
        >
          <div className="border-b border-border p-2">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search simulations…"
              aria-label="Search simulations"
              aria-controls={listboxId}
              aria-activedescendant={activeOptionId}
              className="w-full rounded border border-border bg-surface-light px-2 py-1 text-sm text-foreground placeholder:text-foreground/40"
            />
          </div>
          <ul
            id={listboxId}
            role="listbox"
            aria-label="Simulations"
            className="max-h-72 overflow-y-auto py-1"
          >
            <li
              id={`${listboxId}-opt-0`}
              role="option"
              aria-selected={!simulationId}
              data-testid="picker-option-aggregate"
              className={`cursor-pointer px-3 py-2 text-sm ${
                focusIndex === 0
                  ? "bg-surface-light text-foreground"
                  : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
              }`}
              onMouseDown={(e) => {
                e.preventDefault();
                selectIndex(0);
              }}
              onMouseEnter={() => setFocusIndex(0)}
            >
              {AGGREGATE_LABEL}
            </li>
            {filtered.length === 0 && (
              <li
                role="option"
                aria-selected={false}
                aria-disabled={true}
                className="px-3 py-2 text-xs text-foreground/40"
              >
                No simulations match.
              </li>
            )}
            {filtered.map((sim, i) => {
              const idx = i + 1;
              const active = simulationId === sim.id;
              return (
                <li
                  key={sim.id}
                  id={`${listboxId}-opt-${idx}`}
                  role="option"
                  aria-selected={active}
                  data-testid={`picker-option-${sim.id}`}
                  className={`cursor-pointer px-3 py-2 text-sm flex items-center justify-between gap-2 ${
                    focusIndex === idx
                      ? "bg-surface-light text-foreground"
                      : active
                        ? "text-neon-cyan"
                        : "text-foreground/70 hover:bg-surface-light hover:text-foreground"
                  }`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    selectIndex(idx);
                  }}
                  onMouseEnter={() => setFocusIndex(idx)}
                >
                  <span className="truncate">{sim.name}</span>
                  <span className="text-xs text-foreground/50 shrink-0">
                    {sim.status}
                  </span>
                </li>
              );
            })}
          </ul>
          <div className="border-t border-border p-2 text-right">
            <Link
              href="/simulations"
              onClick={closePopover}
              className="text-xs text-neon-cyan hover:text-neon-magenta transition-colors"
            >
              View all →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
