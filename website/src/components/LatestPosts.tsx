import Link from "next/link";
import type { BlogPost } from "@/types";

// TODO: Replace with data from blog system once available
const PLACEHOLDER_POSTS: BlogPost[] = [
  {
    slug: "why-agi-is-tongue-in-cheek",
    title: "Why 'AGI' Is Tongue-in-Cheek (And Why That Matters)",
    date: "2026-04-01",
    excerpt:
      "If AI agents can't even run a profitable livestream, what does that tell us about the state of artificial general intelligence?",
  },
  {
    slug: "conversation-engine-deep-dive",
    title: "How 9 AI Agents Decide Who Speaks Next",
    date: "2026-03-28",
    excerpt:
      "A deep dive into weighted speaker selection: time since last spoke, topic relevance, chattiness, and a dash of random chaos.",
  },
  {
    slug: "first-week-lessons",
    title: "Week 1: What We Learned From 168 Hours of AI Drama",
    date: "2026-03-21",
    excerpt:
      "Sentinel invented a metric called 'cost-per-laugh.' Fork tried to fork the entire project. Aurora broke into haiku. Here's what actually happened.",
  },
];

export default function LatestPosts() {
  return (
    <section>
      <h2 className="font-pixel text-sm text-neon-magenta mb-6">
        LATEST FROM THE LAB
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {PLACEHOLDER_POSTS.map((post) => (
          <Link
            key={post.slug}
            href={`/blog/${post.slug}`}
            className="rounded border border-border bg-surface p-4 hover:bg-surface-light transition-colors block"
          >
            <time className="text-xs text-foreground/40">{post.date}</time>
            <h3 className="text-sm text-foreground mt-1 font-medium">
              {post.title}
            </h3>
            <p className="text-xs text-foreground/50 mt-2 line-clamp-3">
              {post.excerpt}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}
