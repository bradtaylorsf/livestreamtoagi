import { describe, expect, it } from "vitest";
import {
  getAllPosts,
  getPostBySlug,
  getAllTags,
  getPostsByTag,
  generateRssFeed,
} from "@/lib/blog";

describe("blog", () => {
  describe("getAllPosts", () => {
    it("returns posts sorted by date descending", () => {
      const posts = getAllPosts();
      expect(posts.length).toBeGreaterThan(0);
      for (let i = 1; i < posts.length; i++) {
        expect(new Date(posts[i - 1].date).getTime()).toBeGreaterThanOrEqual(
          new Date(posts[i].date).getTime(),
        );
      }
    });

    it("each post has required frontmatter fields", () => {
      const posts = getAllPosts();
      for (const post of posts) {
        expect(post.slug).toBeTruthy();
        expect(post.title).toBeTruthy();
        expect(post.date).toBeTruthy();
        expect(post.excerpt).toBeTruthy();
        expect(Array.isArray(post.tags)).toBe(true);
        expect(post.author).toBeTruthy();
      }
    });
  });

  describe("getPostBySlug", () => {
    it("returns a post with content", () => {
      const post = getPostBySlug("why-agi-is-tongue-in-cheek");
      expect(post).not.toBeNull();
      expect(post!.title).toContain("Tongue-in-Cheek");
      expect(post!.content).toBeTruthy();
    });

    it("returns null for unknown slug", () => {
      expect(getPostBySlug("nonexistent-post")).toBeNull();
    });
  });

  describe("getAllTags", () => {
    it("returns unique sorted tags", () => {
      const tags = getAllTags();
      expect(tags.length).toBeGreaterThan(0);
      // Check sorted
      for (let i = 1; i < tags.length; i++) {
        expect(tags[i] >= tags[i - 1]).toBe(true);
      }
      // Check unique
      expect(new Set(tags).size).toBe(tags.length);
    });
  });

  describe("getPostsByTag", () => {
    it("filters posts by tag", () => {
      const posts = getPostsByTag("research");
      expect(posts.length).toBeGreaterThan(0);
      for (const post of posts) {
        expect(post.tags).toContain("research");
      }
    });

    it("returns empty array for unknown tag", () => {
      expect(getPostsByTag("nonexistent-tag")).toEqual([]);
    });
  });

  describe("generateRssFeed", () => {
    it("generates valid RSS XML", () => {
      const rss = generateRssFeed("https://example.com");
      expect(rss).toContain('<?xml version="1.0"');
      expect(rss).toContain("<rss");
      expect(rss).toContain("<channel>");
      expect(rss).toContain("<title>Livestream to AGI");
      expect(rss).toContain("<item>");
      expect(rss).toContain("https://example.com/blog/");
    });

    it("includes all posts as items", () => {
      const posts = getAllPosts();
      const rss = generateRssFeed("https://example.com");
      const itemCount = (rss.match(/<item>/g) || []).length;
      expect(itemCount).toBe(posts.length);
    });
  });
});
