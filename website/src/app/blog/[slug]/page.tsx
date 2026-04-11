import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import { MDXRemote } from "next-mdx-remote/rsc";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { getAllPosts, getPostBySlug } from "@/lib/blog";
import JsonLd from "@/components/JsonLd";

export async function generateStaticParams() {
  return getAllPosts().map((post) => ({ slug: post.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const post = getPostBySlug(slug);
  if (!post) return { title: "Post Not Found" };
  return {
    title: post.title,
    description: post.excerpt,
    openGraph: {
      title: post.title,
      description: post.excerpt,
      type: "article",
      ...(post.coverImage ? { images: [post.coverImage] } : {}),
    },
  };
}

export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = getPostBySlug(slug);
  if (!post) notFound();

  return (
    <article className="mx-auto max-w-3xl px-4 py-12">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "BlogPosting",
          headline: post.title,
          description: post.excerpt,
          datePublished: post.date,
          url: `https://livestreamtoagi.com/blog/${post.slug}`,
          author: {
            "@type": "Organization",
            name: "Livestream to AGI",
          },
        }}
      />
      <Link
        href="/blog"
        className="text-xs text-foreground/40 hover:text-foreground/60 transition-colors"
      >
        &larr; Back to blog
      </Link>

      <header className="mt-6 mb-8 space-y-3">
        <h1 className="font-pixel text-sm sm:text-base text-neon-cyan leading-relaxed">
          {post.title}
        </h1>
        <div className="flex items-center gap-3 text-xs text-foreground/50">
          <time>{post.date}</time>
          <span>&middot;</span>
          <span>{post.author}</span>
        </div>
        {post.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {post.tags.map((tag) => (
              <Link
                key={tag}
                href={`/blog?tag=${encodeURIComponent(tag)}`}
                className="text-[10px] px-1.5 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan/70 hover:bg-neon-cyan/20 transition-colors"
              >
                {tag}
              </Link>
            ))}
          </div>
        )}
      </header>

      <div className="prose prose-invert prose-sm max-w-none prose-headings:font-pixel prose-headings:text-xs prose-headings:text-neon-magenta prose-a:text-neon-cyan prose-code:text-neon-green prose-pre:bg-surface prose-pre:border prose-pre:border-border">
        <MDXRemote
          source={post.content}
          options={{
            mdxOptions: {
              remarkPlugins: [remarkGfm],
              rehypePlugins: [rehypeHighlight],
            },
          }}
        />
      </div>
    </article>
  );
}
