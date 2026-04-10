import type { Metadata } from "next";
import Link from "next/link";
import { getAllPosts, getAllTags } from "@/lib/blog";
import BlogPostCard from "@/components/BlogPostCard";

export const metadata: Metadata = {
  title: "Blog — Livestream to AGI",
  description:
    "Research notes, findings, and progress updates from the Livestream to AGI project.",
};

export default async function BlogPage({
  searchParams,
}: {
  searchParams: Promise<{ tag?: string }>;
}) {
  const { tag } = await searchParams;
  const allPosts = getAllPosts();
  const allTags = getAllTags();
  const posts = tag
    ? allPosts.filter((p) => p.tags.includes(tag))
    : allPosts;

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-8">
      <h1 className="font-pixel text-lg text-neon-cyan">BLOG</h1>

      {/* Tag filter bar */}
      {allTags.length > 0 && (
        <div className="flex flex-wrap gap-2" data-testid="tag-filter">
          <Link
            href="/blog"
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              !tag
                ? "border-neon-cyan text-neon-cyan"
                : "border-border text-foreground/40 hover:text-foreground/60"
            }`}
          >
            All
          </Link>
          {allTags.map((t) => (
            <Link
              key={t}
              href={`/blog?tag=${encodeURIComponent(t)}`}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                tag === t
                  ? "border-neon-cyan text-neon-cyan"
                  : "border-border text-foreground/40 hover:text-foreground/60"
              }`}
            >
              {t}
            </Link>
          ))}
        </div>
      )}

      {/* Posts */}
      {posts.length === 0 ? (
        <p className="text-sm text-foreground/40 text-center py-12">
          No posts found{tag ? ` for tag "${tag}"` : ""}.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {posts.map((post) => (
            <BlogPostCard key={post.slug} post={post} />
          ))}
        </div>
      )}
    </div>
  );
}
