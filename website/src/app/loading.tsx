export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      {/* Title skeleton */}
      <div className="h-8 w-64 rounded bg-surface-light animate-pulse mb-8" />

      {/* Content skeletons */}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="rounded-lg border border-border bg-surface p-6"
          >
            <div className="h-4 w-3/4 rounded bg-surface-light animate-pulse mb-4" />
            <div className="h-3 w-full rounded bg-surface-light animate-pulse mb-2" />
            <div className="h-3 w-5/6 rounded bg-surface-light animate-pulse mb-2" />
            <div className="h-3 w-2/3 rounded bg-surface-light animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}
