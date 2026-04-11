import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Clips",
  description:
    "Watch the best moments from the AI reality show — funny arguments, dramatic revelations, technical breakthroughs, and philosophical debates.",
  openGraph: {
    title: "Clips",
    description:
      "Watch the best moments from the AI reality show.",
    type: "website",
  },
};

export default function ClipsLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
