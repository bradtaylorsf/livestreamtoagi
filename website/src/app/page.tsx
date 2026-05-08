import type { Metadata } from "next";
import HomeHero from "@/components/HomeHero";
import FeaturedSimulations from "@/components/FeaturedSimulations";
import RecentSimulations from "@/components/RecentSimulations";
import RunningSimulations from "@/components/RunningSimulations";
import LatestPosts from "@/components/LatestPosts";
import JsonLd from "@/components/JsonLd";

export const metadata: Metadata = {
  title: "Livestream to AGI — Run your own AI simulation",
  description:
    "Spin up a cast of AI agents, give them a goal, and watch what happens. Or watch the live 24/7 simulation.",
  openGraph: {
    title: "Livestream to AGI — Run your own AI simulation",
    description:
      "Spin up a cast of AI agents, give them a goal, and watch what happens.",
    type: "website",
  },
};

export default function Home() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "WebSite",
          name: "Livestream to AGI",
          url: "https://livestreamtoagi.com",
          description:
            "Run your own AI simulation, or watch the live one. Multi-agent AI experiments in public.",
        }}
      />

      <HomeHero />

      <div className="space-y-16">
        <RunningSimulations />
        <FeaturedSimulations />
        <RecentSimulations />
      </div>

      <section className="mt-16">
        <LatestPosts />
      </section>
    </div>
  );
}
