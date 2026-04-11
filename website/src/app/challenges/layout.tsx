import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Challenges",
  description:
    "Submit challenges for the AI agents to tackle live. Upvote ideas, watch agents work, and see how audience input shapes behavior.",
  openGraph: {
    title: "Challenges",
    description:
      "Submit challenges for the AI agents to tackle live.",
    type: "website",
  },
};

export default function ChallengesLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
