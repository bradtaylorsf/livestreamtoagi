import type { MetadataRoute } from "next";
import { getAllPosts } from "@/lib/blog";
import { getAllAgentIds } from "@/lib/agent-data";

const BASE_URL = "https://livestreamtoagi.com";

export default function sitemap(): MetadataRoute.Sitemap {
  const staticPages = [
    "",
    "/about",
    "/agents",
    "/blog",
    "/challenges",
    "/clips",
    "/conversations",
    "/donate",
    "/evals",
    "/ethics",
    "/lore",
    "/safety",
    "/world",
  ].map((path) => ({
    url: `${BASE_URL}${path}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
  }));

  const agentPages = getAllAgentIds().map((id) => ({
    url: `${BASE_URL}/agents/${id}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
  }));

  const blogPages = getAllPosts().map((post) => ({
    url: `${BASE_URL}/blog/${post.slug}`,
    lastModified: new Date(post.date),
    changeFrequency: "monthly" as const,
  }));

  return [...staticPages, ...agentPages, ...blogPages];
}
