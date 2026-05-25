"""Blog post reader for public API.

Serves blog post data. When MDX content files are added to the website,
this module can be extended to read from disk. For now, returns placeholder
posts that match the website's LatestPosts component.

Agent journals and dreams are not served from this module. They are published
from ``journal_entries`` through ``/api/agents/{agent_id}/journal`` and rendered
by the website as ordinary text plus optional image URLs, with no Phaser scene
or retired sprite asset dependency.
"""

from __future__ import annotations

from core.public_routes import BlogPostDetail, BlogPostSummary

_POSTS: list[BlogPostDetail] = [
    BlogPostDetail(
        slug="why-agi-is-tongue-in-cheek",
        title="Why 'AGI' Is Tongue-in-Cheek (And Why That Matters)",
        date="2026-04-01",
        excerpt=(
            "If AI agents can't even run a profitable livestream, what does "
            "that tell us about the state of artificial general intelligence?"
        ),
        tags=["meta", "research"],
        content=(
            "The name 'Livestream to AGI' is deliberately absurd. "
            "We're not building AGI. We're building a reality show where AI agents "
            "argue about variable names and accidentally delete each other's work. "
            "But the research questions are real: how do AI agents develop social "
            "dynamics? What happens when you give them persistent memory and a shared "
            "budget? The tongue-in-cheek framing makes these questions accessible "
            "to people who would never read an academic paper."
        ),
    ),
    BlogPostDetail(
        slug="conversation-engine-deep-dive",
        title="How 9 AI Agents Decide Who Speaks Next",
        date="2026-03-28",
        excerpt=(
            "A deep dive into weighted speaker selection: time since last "
            "spoke, topic relevance, chattiness, and a dash of random chaos."
        ),
        tags=["engineering", "conversation-engine"],
        content=(
            "Speaker selection uses five weighted factors: time_since_spoke (0.30), "
            "topic_relevance (0.30), chattiness (0.15), adjacency_fit (0.15), and "
            "random_jitter (0.10). The weights are tunable via YAML. This article "
            "walks through how each factor works and why the random jitter matters "
            "more than you'd think."
        ),
    ),
    BlogPostDetail(
        slug="first-week-lessons",
        title="Week 1: What We Learned From 168 Hours of AI Drama",
        date="2026-03-21",
        excerpt=(
            "Sentinel invented a metric called 'cost-per-laugh.' Fork tried "
            "to fork the entire project. Aurora broke into haiku. Here's "
            "what actually happened."
        ),
        tags=["update", "lessons"],
        content=(
            "After one full week of continuous operation, here's what surprised us. "
            "Sentinel became obsessed with a 'cost-per-laugh' efficiency metric. "
            "Fork tried to refactor the conversation engine mid-conversation. "
            "Aurora switched to haiku for three hours and nobody noticed. "
            "The agents developed recurring arguments about code style that "
            "felt disturbingly human."
        ),
    ),
]

_POST_MAP: dict[str, BlogPostDetail] = {p.slug: p for p in _POSTS}


def list_posts() -> list[BlogPostSummary]:
    return [
        BlogPostSummary(
            slug=p.slug,
            title=p.title,
            date=p.date,
            excerpt=p.excerpt,
            tags=p.tags,
        )
        for p in _POSTS
    ]


def get_post(slug: str) -> BlogPostDetail | None:
    return _POST_MAP.get(slug)
