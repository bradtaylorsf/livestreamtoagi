import { generateRssFeed } from "@/lib/blog";

export async function GET() {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://livestreamtoagi.com";
  const xml = generateRssFeed(siteUrl);
  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
    },
  });
}
