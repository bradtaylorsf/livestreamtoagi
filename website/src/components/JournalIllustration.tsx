"use client";

import { useState } from "react";

export type JournalIllustrationStatus = "image" | "missing" | "failed";

interface JournalIllustrationFrameProps {
  imageUrl: string | null | undefined;
  label: string;
  status: JournalIllustrationStatus;
  onImageError?: () => void;
  className?: string;
}

interface JournalIllustrationProps {
  imageUrl: string | null | undefined;
  label: string;
  className?: string;
}

export function getJournalIllustrationStatus(
  imageUrl: string | null | undefined,
  imageLoadFailed: boolean,
): JournalIllustrationStatus {
  if (!imageUrl) return "missing";
  return imageLoadFailed ? "failed" : "image";
}

export function JournalIllustrationFrame({
  imageUrl,
  label,
  status,
  onImageError,
  className = "",
}: JournalIllustrationFrameProps) {
  const fallbackText =
    status === "failed" ? "Illustration unavailable" : "Text-only journal";
  const frameClass =
    "mb-3 aspect-square w-full max-w-sm overflow-hidden rounded border " +
    "border-border bg-surface-light";

  return (
    <figure
      className={`${frameClass} ${className}`}
      data-illustration-status={status}
    >
      {status === "image" && imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imageUrl}
          alt={label}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={onImageError}
        />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2 px-4 text-center">
          <div
            aria-hidden="true"
            className="h-8 w-8 rounded border border-border bg-surface"
          />
          <span className="text-xs text-foreground/45">{fallbackText}</span>
        </div>
      )}
    </figure>
  );
}

export default function JournalIllustration({
  imageUrl,
  label,
  className,
}: JournalIllustrationProps) {
  const [imageLoadFailed, setImageLoadFailed] = useState(false);
  const status = getJournalIllustrationStatus(imageUrl, imageLoadFailed);

  return (
    <JournalIllustrationFrame
      imageUrl={imageUrl}
      label={label}
      status={status}
      className={className}
      onImageError={() => setImageLoadFailed(true)}
    />
  );
}
