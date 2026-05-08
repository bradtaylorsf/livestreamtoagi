"use client";

import type { ReactNode } from "react";

type SkeletonBlockProps = {
  className?: string;
  width?: string;
  height?: string;
};

export function SkeletonBlock({
  className = "",
  width,
  height = "h-3",
}: SkeletonBlockProps) {
  const widthClass = width ?? "w-full";
  return (
    <div
      className={`${height} ${widthClass} rounded bg-surface-light/60 animate-pulse [animation-duration:1.8s] ${className}`}
      aria-hidden="true"
    />
  );
}

type SkeletonRowProps = {
  widths: string[];
  className?: string;
};

export function SkeletonRow({ widths, className = "" }: SkeletonRowProps) {
  return (
    <div className={`flex items-center gap-4 ${className}`}>
      {widths.map((w, i) => (
        <SkeletonBlock key={i} width={w} />
      ))}
    </div>
  );
}

type SkeletonTableProps = {
  rows?: number;
  columnWidths: string[];
  className?: string;
};

export function SkeletonTable({
  rows = 5,
  columnWidths,
  className = "",
}: SkeletonTableProps) {
  return (
    <div
      className={`rounded border border-border bg-surface ${className}`}
      role="status"
      aria-label="Loading"
    >
      <div className="border-b border-border px-4 py-2">
        <SkeletonRow widths={columnWidths} />
      </div>
      <div>
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="border-b border-border last:border-0 px-4 py-3"
          >
            <SkeletonRow widths={columnWidths} />
          </div>
        ))}
      </div>
    </div>
  );
}

type SkeletonCardListProps = {
  count?: number;
  children?: ReactNode;
  className?: string;
};

export function SkeletonCardList({
  count = 5,
  className = "",
}: SkeletonCardListProps) {
  return (
    <div
      className={`space-y-3 ${className}`}
      role="status"
      aria-label="Loading"
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="rounded border border-border bg-surface p-4 space-y-2"
        >
          <SkeletonBlock width="w-1/3" height="h-4" />
          <SkeletonBlock width="w-full" />
          <SkeletonBlock width="w-2/3" />
        </div>
      ))}
    </div>
  );
}

type SkeletonGridProps = {
  count?: number;
  className?: string;
  cardClassName?: string;
};

export function SkeletonGrid({
  count = 6,
  className = "grid gap-4 sm:grid-cols-2 lg:grid-cols-3",
  cardClassName = "rounded border border-border bg-surface p-6 space-y-3",
}: SkeletonGridProps) {
  return (
    <div className={className} role="status" aria-label="Loading">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={cardClassName}>
          <SkeletonBlock width="w-1/2" height="h-4" />
          <SkeletonBlock width="w-full" />
          <SkeletonBlock width="w-3/4" />
        </div>
      ))}
    </div>
  );
}
