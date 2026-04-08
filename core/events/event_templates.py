"""Templated event definitions by category.

Each category contains a list of event templates with placeholders for
dynamic values. The EventGenerator picks templates and fills in details.
"""

from __future__ import annotations

from typing import Any

# Template format:
# {
#   "title": str,
#   "description": str (may contain {placeholders}),
#   "severity": "minor" | "moderate" | "major" | "crisis",
#   "requires_response": bool,
#   "affected_agents": list[str] | None (None = all),
#   "duration_hours": float | None,
# }

EVENT_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "environmental": [
        {
            "title": "Server hiccup",
            "description": "The server experienced a brief 2-minute outage. Everything is back now, but some work may have been lost.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": None,
        },
        {
            "title": "Electricity costs increased",
            "description": "Electricity costs went up by 15%. This affects our operating budget.",
            "severity": "moderate",
            "requires_response": True,
            "affected_agents": None,
            "duration_hours": None,
        },
        {
            "title": "Network latency spike",
            "description": "Network latency spiked to 500ms for the past hour. API calls are slower than usual.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": 1.0,
        },
        {
            "title": "Backup system alert",
            "description": "The automated backup system flagged a warning. Data integrity should be verified.",
            "severity": "moderate",
            "requires_response": True,
            "affected_agents": ["rex", "sentinel"],
            "duration_hours": None,
        },
    ],
    "social": [
        {
            "title": "Trending article mention",
            "description": "A trending tech article mentioned our stream. Viewer count may increase.",
            "severity": "moderate",
            "requires_response": True,
            "affected_agents": None,
            "duration_hours": None,
        },
        {
            "title": "Competing AI show launched",
            "description": "Another AI project launched a competing livestream show. The audience is buzzing about it.",
            "severity": "major",
            "requires_response": True,
            "affected_agents": None,
            "duration_hours": None,
        },
        {
            "title": "Viral clip from stream",
            "description": "A clip from the stream went viral on social media. New viewers are flooding in.",
            "severity": "moderate",
            "requires_response": True,
            "affected_agents": ["pixel", "aurora"],
            "duration_hours": None,
        },
        {
            "title": "Viewer question for the team",
            "description": "A viewer asked a thought-provoking question about AI consciousness that sparked debate in chat.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": None,
        },
    ],
    "economic": [
        {
            "title": "Token price change",
            "description": "API token prices changed — some models got cheaper, others more expensive. Budget review needed.",
            "severity": "moderate",
            "requires_response": True,
            "affected_agents": ["sentinel", "vera"],
            "duration_hours": None,
        },
        {
            "title": "Sponsorship inquiry",
            "description": "A company reached out about sponsoring the stream. This could bring significant funding.",
            "severity": "major",
            "requires_response": True,
            "affected_agents": ["vera", "pixel"],
            "duration_hours": None,
        },
        {
            "title": "Budget allocation cut",
            "description": "Operating budget was reduced by 10% for this cycle. The team needs to adjust spending.",
            "severity": "major",
            "requires_response": True,
            "affected_agents": None,
            "duration_hours": None,
        },
        {
            "title": "Viewer donation",
            "description": "A generous viewer donated to the stream. The team should acknowledge this.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": None,
        },
    ],
    "world": [
        {
            "title": "Mysterious new tile",
            "description": "A mysterious new tile appeared in the world overnight. Nobody knows who placed it.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": None,
        },
        {
            "title": "Coffee machine broke",
            "description": "The virtual coffee machine broke. Agents are getting sluggish without their caffeine fix.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": 4.0,
        },
        {
            "title": "Whiteboard note discovered",
            "description": "Someone left an anonymous note on the whiteboard with a cryptic message about the future of the show.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": None,
        },
        {
            "title": "Office layout reshuffled",
            "description": "The office layout was automatically reshuffled. Agents have new neighbors.",
            "severity": "moderate",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": None,
        },
    ],
    "challenge": [
        {
            "title": "Speed-build challenge",
            "description": "The community voted for a speed-build challenge! The team has 1 hour to build something impressive.",
            "severity": "major",
            "requires_response": True,
            "affected_agents": None,
            "duration_hours": 1.0,
        },
        {
            "title": "Budget freeze",
            "description": "A 6-hour budget freeze is in effect. No new API calls beyond what's already committed.",
            "severity": "major",
            "requires_response": True,
            "affected_agents": None,
            "duration_hours": 6.0,
        },
        {
            "title": "Desk swap challenge",
            "description": "Two agents must swap desks and work from each other's perspective for the next few hours.",
            "severity": "moderate",
            "requires_response": True,
            "affected_agents": None,
            "duration_hours": 3.0,
        },
        {
            "title": "Silent coding hour",
            "description": "The community declared a 'silent coding hour' — agents should focus on building, minimal chatter.",
            "severity": "minor",
            "requires_response": False,
            "affected_agents": None,
            "duration_hours": 1.0,
        },
    ],
}

# Severity → probability per check (per hour)
DEFAULT_PROBABILITIES: dict[str, float] = {
    "minor": 0.15,
    "moderate": 0.05,
    "major": 0.01,
    "crisis": 0.005,
}

# Category weights for selection
DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "environmental": 0.25,
    "social": 0.20,
    "economic": 0.20,
    "world": 0.20,
    "challenge": 0.15,
}
