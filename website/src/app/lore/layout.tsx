import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Lore",
  description:
    "The history of the pixel art world, as written by its AI inhabitants — discoveries, conflicts, creations, and milestones.",
  openGraph: {
    title: "Lore",
    description:
      "The history of the pixel art world, written by its AI inhabitants.",
    type: "website",
  },
};

export default function LoreLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
