import Link from "next/link";
import type { BlogPostMeta } from "@/lib/blog";

export default function BlogPostCard({ post }: { post: BlogPostMeta }) {
  return (
    <Link
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
      {post.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-3">
          {post.tags.map((tag) => (
            <span
              key={tag}
              className="text-[10px] px-1.5 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan/70"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
