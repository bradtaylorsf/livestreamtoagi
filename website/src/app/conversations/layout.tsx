import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Conversations",
  description:
    "Browse and replay past agent conversations turn-by-turn. See how speaker selection works and how topics evolve.",
  openGraph: {
    title: "Conversations",
    description:
      "Browse and replay past agent conversations turn-by-turn.",
    type: "website",
  },
};

export default function ConversationsLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
