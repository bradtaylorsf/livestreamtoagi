# Tool Definitions: Livestream to AGI

Every tool an agent can use, what it does, which agents have access, and the estimated cost per call.

## Core tools (available to all agents, always loaded)

### send_message
```yaml
name: send_message
description: "Send a message to another agent or to the group"
parameters:
  to: string  # agent_id or "group"
  message: string
  tone: string  # "casual", "urgent", "professional", "dramatic", "sarcastic"
cost: 0 tokens (internal routing only)
access: all agents
```

### read_core_memory
```yaml
name: read_core_memory
description: "Read your own core memory (Tier 1)"
parameters: none
returns: string  # your full core memory
cost: 0 (already in context)
access: all agents
```

### update_core_memory
```yaml
name: update_core_memory
description: "Update a section of your core memory"
parameters:
  section: string  # "relationships", "key_learnings", "goals", "running_jokes"
  agent_target: string  # only for relationships section
  content: string
cost: ~100 tokens (write to DB)
access: all agents
restrictions: "core memory must stay under 3,000 tokens total"
```

### recall_memory
```yaml
name: recall_memory
description: "Search your past memories for relevant context"
parameters:
  query: string  # what you're trying to remember
  limit: int  # max results (default 3)
returns: list of summaries with transcript_ids
cost: ~$0.0001 (embedding call)
access: all agents
```

### retrieve_transcript
```yaml
name: retrieve_transcript
description: "Get the full transcript of a past interaction (from a recall memory)"
parameters:
  transcript_id: int
returns: string  # full transcript
cost: 0 (DB read, but adds tokens to context)
access: all agents
note: "Use sparingly — adds 1,000-5,000 tokens to your context"
```

### update_task_status
```yaml
name: update_task_status
description: "Update the status of your current task"
parameters:
  task_id: int
  status: string  # "in_progress", "completed", "failed", "blocked"
  notes: string
cost: 0
access: all agents
```

### get_world_state
```yaml
name: get_world_state
description: "Get current state of the world — agent locations, active tasks, recent events"
parameters: none
returns: JSON with agent positions, active tasks, recent events, budget status
cost: 0 (Redis read)
access: all agents
```

### get_audience_status
```yaml
name: get_audience_status
description: "Get current viewer count, recent chat highlights, active polls"
parameters: none
returns: JSON with viewer_count, recent_chat_messages, active_polls
cost: 0 (cached from Twitch API)
access: all agents (but Pixel is the primary user)
```

## Building tools (available to specific agents, loaded on-demand)

### execute_code
```yaml
name: execute_code
description: "Execute Python or JavaScript code in a sandboxed Docker container"
parameters:
  language: string  # "python" or "javascript"
  code: string
  timeout: int  # max seconds (default 30, max 120)
returns: stdout, stderr, exit_code
cost: 0 (self-hosted sandbox)
access: [rex, fork, sentinel]
restrictions:
  - no network access by default
  - 512MB memory limit
  - 1 CPU core
  - read-only filesystem except /tmp
  - max 120 second execution
```

### generate_tilemap
```yaml
name: generate_tilemap
description: "Execute tilemap generation code and register the output as a new world chunk"
parameters:
  name: string  # chunk name (e.g., "library")
  code: string  # Python code that outputs chunk JSON
  description: string  # creative brief for the chunk
returns: chunk_id, preview_url
cost: ~$0.001 (code execution)
access: [rex, fork]
note: "Code must output valid chunk JSON to stdout"
```

### generate_pixel_art
```yaml
name: generate_pixel_art
description: "Generate pixel art assets via PixelLab API"
parameters:
  prompt: string  # description of what to generate
  style: string  # "tileset", "sprite", "object", "decoration"
  size: string  # "16x16", "32x32", "64x64"
  palette: string  # optional — reference palette name
returns: image_url, asset_id
cost: ~$0.003-0.01 per image
access: [aurora, rex]
restrictions: "must include project style guide in prompt"
```

### web_search
```yaml
name: web_search
description: "Search the web for information"
parameters:
  query: string
  max_results: int  # default 5
returns: list of {title, url, snippet}
cost: ~$0.001-0.01 per search (model-dependent)
access: [pixel, grok, aurora, vera]
```

### fetch_url
```yaml
name: fetch_url
description: "Fetch and read content from a specific URL"
parameters:
  url: string
returns: text content of the page (truncated to 4,000 tokens)
cost: ~$0.001
access: [pixel, grok]
```

## Communication tools (audience-facing)

### send_chat_message
```yaml
name: send_chat_message
description: "Send a message to Twitch/YouTube chat"
parameters:
  message: string
cost: 0
access: [pixel, sentinel, vera]  # only designated chat agents
restrictions: "always passes through Overseer filter first"
```

### create_poll
```yaml
name: create_poll
description: "Create a Twitch poll for audience voting"
parameters:
  title: string
  options: list[string]  # 2-5 options
  duration: int  # seconds (default 120)
returns: poll_id
cost: 0
access: [vera, pixel]
restrictions: "max 1 active poll at a time"
```

### get_poll_results
```yaml
name: get_poll_results
description: "Get results of a completed poll"
parameters:
  poll_id: string
returns: {options: [{name, votes, percentage}], total_votes, winner}
cost: 0
access: all agents
```

## Alpha-specific tools

### dispatch_alpha
```yaml
name: dispatch_alpha
description: "Send Alpha the wolf to do a small errand"
parameters:
  task: string  # short task description
  urgency: string  # "when_free" or "now"
returns: task_id (Alpha will report back when done)
cost: ~$0.001-0.01 depending on task
access: all agents except alpha itself
restrictions: "Alpha can only handle tasks under 60 seconds"
```

## Self-modification tools

### propose_self_modification
```yaml
name: propose_self_modification
description: "Propose a change to your own personality, behaviors, or configuration"
parameters:
  file: string  # "behaviors.yaml", "system_prompt.md", or "relationships.json"
  change_description: string
  new_content: string  # the proposed new content for the section
returns: proposal_id, status ("queued_for_review")
cost: 0
access: all agents
restrictions:
  - cannot modify other agents' files
  - cannot modify permissions or the Overseer
  - changes are queued, not immediate
  - auto-approved after 4 hours if no human rejection (month 2+)
  - human review required for first 2 months
```

### view_evolution_log
```yaml
name: view_evolution_log
description: "View the history of your own self-modifications"
parameters:
  limit: int  # default 10
returns: list of {date, change_description, status, impact_notes}
cost: 0
access: all agents (can view own log only)
```

## Revenue and marketing tools

### get_revenue_status
```yaml
name: get_revenue_status
description: "Get current revenue breakdown and financial health"
parameters: none
returns: {
  monthly_revenue: {subs, donations, sponsorships, total},
  monthly_costs: {api, infrastructure, tools, total},
  burn_rate: float,
  runway_days: int,
  trend: "improving" | "stable" | "declining"
}
cost: 0
access: [sentinel, vera]
```

### draft_social_post
```yaml
name: draft_social_post
description: "Draft a social media post (requires human approval before posting)"
parameters:
  platform: string  # "twitter", "discord", "youtube_community"
  content: string
  media_urls: list[string]  # optional
returns: draft_id, status ("pending_human_review")
cost: 0
access: [aurora, pixel, grok]
restrictions: "all social posts require human approval for first 3 months"
```

### draft_email
```yaml
name: draft_email
description: "Draft an email for sponsorship outreach or grant applications"
parameters:
  to: string
  subject: string
  body: string
returns: draft_id, status ("pending_human_review")
cost: 0
access: [aurora, vera, pixel]
restrictions: "all external emails require human approval"
```
