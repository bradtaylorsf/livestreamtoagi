import fs from "fs";
import path from "path";
import matter from "gray-matter";

export interface BlogPostMeta {
  slug: string;
  title: string;
  date: string;
  excerpt: string;
  tags: string[];
  author: string;
  coverImage?: string;
}

export interface BlogPostFull extends BlogPostMeta {
  content: string;
}

const BLOG_DIR = path.join(process.cwd(), "content", "blog");

function parseFrontmatter(slug: string, fileContent: string): BlogPostFull {
  const { data, content } = matter(fileContent);
  return {
    slug,
    title: data.title ?? slug,
    date: data.date ? String(data.date) : "",
    excerpt: data.excerpt ?? "",
    tags: Array.isArray(data.tags) ? data.tags : [],
    author: data.author ?? "Brad Taylor",
    coverImage: data.coverImage,
    content,
  };
}

export function getAllPosts(): BlogPostMeta[] {
  if (!fs.existsSync(BLOG_DIR)) return [];
  const files = fs.readdirSync(BLOG_DIR).filter((f) => f.endsWith(".mdx"));
  const posts = files.map((file) => {
    const slug = file.replace(/\.mdx$/, "");
    const raw = fs.readFileSync(path.join(BLOG_DIR, file), "utf-8");
    const { content: _content, ...meta } = parseFrontmatter(slug, raw);
    return meta;
  });
  return posts.sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
  );
}

export function getPostBySlug(slug: string): BlogPostFull | null {
  const filePath = path.join(BLOG_DIR, `${slug}.mdx`);
  if (!fs.existsSync(filePath)) return null;
  const raw = fs.readFileSync(filePath, "utf-8");
  return parseFrontmatter(slug, raw);
}

export function getAllTags(): string[] {
  const posts = getAllPosts();
  const tagSet = new Set<string>();
  for (const post of posts) {
    for (const tag of post.tags) {
      tagSet.add(tag);
    }
  }
  return Array.from(tagSet).sort();
}

export function getPostsByTag(tag: string): BlogPostMeta[] {
  return getAllPosts().filter((p) => p.tags.includes(tag));
}

export function generateRssFeed(siteUrl: string): string {
  const posts = getAllPosts();
  const items = posts
    .map(
      (p) => `    <item>
      <title>${escapeXml(p.title)}</title>
      <link>${siteUrl}/blog/${p.slug}</link>
      <description>${escapeXml(p.excerpt)}</description>
      <pubDate>${new Date(p.date).toUTCString()}</pubDate>
      <guid>${siteUrl}/blog/${p.slug}</guid>
    </item>`,
    )
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Livestream to AGI — Blog</title>
    <link>${siteUrl}/blog</link>
    <description>Research notes, findings, and progress updates from the Livestream to AGI project.</description>
    <atom:link href="${siteUrl}/blog/rss.xml" rel="self" type="application/rss+xml"/>
${items}
  </channel>
</rss>`;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
