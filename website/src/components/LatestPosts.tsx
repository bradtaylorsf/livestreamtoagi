import Link from "next/link";
import { getAllPosts } from "@/lib/blog";
import BlogPostCard from "@/components/BlogPostCard";

export default function LatestPosts() {
  const posts = getAllPosts().slice(0, 3);

  if (posts.length === 0) {
    return null;
  }

  return (
    <section>
      <h2 className="font-pixel text-sm text-neon-magenta mb-6">
        LATEST FROM THE LAB
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {posts.map((post) => (
          <BlogPostCard key={post.slug} post={post} />
        ))}
      </div>
      <div className="mt-4 text-right">
        <Link
          href="/blog"
          className="text-xs text-foreground/40 hover:text-neon-cyan transition-colors"
        >
          View all posts &rarr;
        </Link>
      </div>
    </section>
  );
}
