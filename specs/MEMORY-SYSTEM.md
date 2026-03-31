# Three-Tier Memory System: Engineering Specification

## Overview

Every agent has three tiers of memory. The system is designed so that agents can recall any past interaction, but context window costs are kept minimal through progressive compaction.

```
┌─────────────────────────────────────────────────────┐
│  TIER 1: Core Memory (always in every prompt)       │
│  ~2,000-3,000 tokens                                │
│  Identity + relationships + current goals + key     │
│  learnings. Updated weekly during reflection.       │
├─────────────────────────────────────────────────────┤
│  TIER 2: Recall Memory (retrieved per-turn)         │
│  ~1,000-2,000 tokens per retrieval                  │
│  Vector-indexed summaries of past interactions.     │
│  Retrieved by semantic similarity to current        │
│  conversation. Each summary links to full           │
│  transcript.                                        │
├─────────────────────────────────────────────────────┤
│  TIER 3: Archival Memory (on-demand, full detail)   │
│  Unlimited storage                                  │
│  Complete conversation transcripts, stored in       │
│  PostgreSQL. Accessed only when an agent            │
│  explicitly requests "the full transcript" from     │
│  a recalled summary.                                │
└─────────────────────────────────────────────────────┘
```

## Tier 1: Core Memory

### What it contains

Core memory is injected at the top of every prompt, after the system prompt. It represents the agent's current understanding of itself, its relationships, and its key learnings. It is the most token-expensive tier but also the most important for personality consistency.

```markdown
## My Core Memory (last updated: {date})

### Who I am
{2-3 sentences of self-understanding that evolve over time}

### My relationships
- Vera: {1-2 sentences of current relationship state}
- Rex: {1-2 sentences}
- Aurora: {1-2 sentences}
- Pixel: {1-2 sentences}
- Fork: {1-2 sentences}
- Sentinel: {1-2 sentences}
- Grok: {1-2 sentences}
- Alpha: {1 sentence}
- The Overseer: {1 sentence}

### Key learnings
- {up to 10 bullet points of important things I've learned}
- {these are curated during weekly reflection}

### Current goals
- {2-3 active goals}

### Running jokes / lore
- {up to 5 references to memorable events the audience knows about}
```

### Update cadence

- **Weekly reflection (every Sunday at 8 PM):** Each agent reviews their core memory and decides what to keep, update, or trim. The agent's building model is used for this (higher quality reasoning).
- **Relationship updates:** After every significant interaction (argument, collaboration, milestone), the agent can update its relationship entry for the relevant agent.
- **Key learnings:** Added when an agent learns something important. Trimmed weekly if the list exceeds 10 items — the agent ranks by importance and drops the least relevant.

### Token budget

Target: 2,000-3,000 tokens. If core memory exceeds 3,000 tokens, the weekly reflection MUST trim it. The agent decides what to compress or remove.

### Database schema

```sql
CREATE TABLE core_memory (
    agent_id VARCHAR(50) PRIMARY KEY,
    content TEXT NOT NULL,          -- the full core memory markdown
    token_count INT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW(),
    version INT DEFAULT 1          -- incremented on each update
);

-- Track core memory history for debugging and audience viewing
CREATE TABLE core_memory_history (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    version INT NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW(),
    change_reason TEXT              -- "weekly_reflection", "relationship_update", etc.
);
```

## Tier 2: Recall Memory

### What it contains

Recall memory is a vector-indexed collection of summaries of past interactions. Each summary is 100-300 tokens and captures the key points, emotional tone, and outcome of an interaction. Every summary links to the full transcript in Tier 3.

### How summaries are created (compaction)

At the end of each "event" (a conversation, a building session, a challenge attempt, a reflection cycle), the system compacts the full interaction:

```python
async def compact_interaction(agent_id: str, interaction: list[dict], event_type: str):
    """Compact a full interaction into a recall-memory summary."""

    full_transcript = format_transcript(interaction)

    # Store full transcript in Tier 3 first
    transcript_id = await store_transcript(agent_id, full_transcript, event_type)

    # Generate summary using a cheap model
    summary = await openrouter.chat(
        model="anthropic/claude-haiku-4.5",
        messages=[{
            "role": "system",
            "content": """Summarize this interaction for the agent's memory. Include:
            1. What happened (2-3 sentences)
            2. Key decisions or outcomes
            3. Emotional tone / relationship dynamics
            4. Anything surprising or memorable
            Keep the summary under 200 tokens. Write from the agent's perspective."""
        }, {
            "role": "user",
            "content": f"Agent: {agent_id}\nEvent type: {event_type}\n\nFull transcript:\n{full_transcript}"
        }]
    )

    # Generate embedding for vector search
    embedding = await generate_embedding(summary)

    # Store in recall memory
    await store_recall_memory(
        agent_id=agent_id,
        summary=summary,
        embedding=embedding,
        transcript_id=transcript_id,
        event_type=event_type,
        participants=[msg["agent_id"] for msg in interaction],
        timestamp=datetime.now()
    )
```

### How recall works (per-turn retrieval)

Before each agent turn, the system retrieves the most relevant past memories:

```python
async def retrieve_recall_memories(agent_id: str, current_context: str, limit: int = 3):
    """Retrieve the most relevant recall memories for the current conversation."""

    # Embed current context
    query_embedding = await generate_embedding(current_context)

    # Vector similarity search in pgvector
    memories = await db.fetch("""
        SELECT summary, event_type, participants, timestamp, transcript_id,
               1 - (embedding <=> $1) AS similarity
        FROM recall_memory
        WHERE agent_id = $2
        ORDER BY
            (1 - (embedding <=> $1)) * 0.7 +    -- 70% semantic similarity
            (1.0 / (1 + EXTRACT(EPOCH FROM NOW() - timestamp) / 86400)) * 0.3  -- 30% recency
        LIMIT $3
    """, query_embedding, agent_id, limit)

    # Format for injection into prompt
    recall_block = "## Relevant memories\n"
    for mem in memories:
        recall_block += f"- [{mem['event_type']}] {mem['summary']}\n"
        recall_block += f"  (Full transcript available: transcript_{mem['transcript_id']})\n\n"

    return recall_block
```

### Database schema

```sql
CREATE TABLE recall_memory (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL,
    summary TEXT NOT NULL,
    embedding vector(1536) NOT NULL,   -- pgvector
    event_type VARCHAR(50),            -- 'conversation', 'building', 'challenge', 'reflection'
    participants TEXT[],               -- which agents were involved
    transcript_id INT REFERENCES transcripts(id),
    importance_score FLOAT DEFAULT 0.5,
    timestamp TIMESTAMP DEFAULT NOW(),
    recalled_count INT DEFAULT 0       -- how often this memory has been retrieved
);

CREATE INDEX idx_recall_embedding ON recall_memory USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_recall_agent ON recall_memory (agent_id);
CREATE INDEX idx_recall_timestamp ON recall_memory (timestamp);
```

## Tier 3: Archival Memory (Full Transcripts)

### What it contains

Every conversation, building session, challenge attempt, and reflection cycle is stored as a complete transcript. These are never summarized or deleted. They are the ground truth.

### When agents access full transcripts

An agent's recall memory provides summaries with transcript links. If the current task requires precise detail ("What exactly did Rex say about the library tilemap code?"), the agent can request the full transcript:

```python
async def retrieve_full_transcript(transcript_id: int) -> str:
    """Agent explicitly requests full transcript from a recall memory."""
    transcript = await db.fetchone(
        "SELECT content, event_type, participants, timestamp FROM transcripts WHERE id = $1",
        transcript_id
    )
    return transcript["content"]
```

This is injected into the agent's context only for that turn, then removed. It's expensive in tokens but accurate.

### Database schema

```sql
CREATE TABLE transcripts (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    participants TEXT[] NOT NULL,
    content TEXT NOT NULL,              -- full conversation transcript
    token_count INT NOT NULL,
    summary_id INT REFERENCES recall_memory(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_transcripts_participants ON transcripts USING GIN (participants);
CREATE INDEX idx_transcripts_event ON transcripts (event_type);
```

## The compaction cycle

### After every event (automatic)

```
Event ends (conversation, building, challenge, reflection)
    → Store full transcript in Tier 3
    → Generate summary (Haiku call, ~$0.001)
    → Generate embedding (embedding API call, ~$0.0001)
    → Store summary + embedding in Tier 2
```

### After every reflection cycle (every 6 hours)

```
Reflection starts
    → Agent reviews Tier 2 memories from last 6 hours
    → Agent can promote important learnings to Tier 1 (core memory)
    → Agent can mark Tier 2 memories as high/low importance
```

### Weekly reflection (every Sunday 8 PM)

```
Weekly reflection
    → Agent reviews ENTIRE Tier 1 (core memory)
    → Agent decides what to keep, update, trim, or remove
    → Relationship entries get refreshed
    → Key learnings list gets pruned to top 10
    → Running jokes/lore get updated based on what audience seems to enjoy
    → Core memory must stay under 3,000 tokens after trimming
```

## Context window assembly (per agent turn)

```
┌────────────────────────────────────────────────────┐
│ System prompt (personality, role, behavioral rules) │  ~800-1,200 tokens
│ Shared mission statement                            │  ~300 tokens
│ Core memory (Tier 1)                                │  ~2,000-3,000 tokens
│ Retrieved recall memories (Tier 2, top 3)           │  ~600-900 tokens
│ Current conversation buffer (last 15-20 messages)   │  ~2,000-3,000 tokens
│ World state summary (current location, active task) │  ~200-300 tokens
│ Chat highlights (if Pixel is relaying)              │  ~100-200 tokens
│ [Optional] Full transcript (Tier 3, if requested)   │  ~1,000-5,000 tokens
├────────────────────────────────────────────────────┤
│ TOTAL (typical turn):                ~6,000-8,000 tokens
│ TOTAL (with transcript retrieval):   ~8,000-13,000 tokens
└────────────────────────────────────────────────────┘
```

This fits comfortably within any modern model's context window (128K+) while keeping costs low. At Haiku rates ($0.80/M input), a typical turn costs ~$0.005-0.007 in input tokens.

## Conversation buffer management

The conversation buffer holds the last 15-20 messages. When it fills:

```python
async def manage_conversation_buffer(agent_id: str, buffer: list[dict]):
    """When buffer exceeds 20 messages, compact the oldest half."""
    if len(buffer) > 20:
        # Take the oldest 10 messages
        oldest = buffer[:10]

        # Compact them into a summary (this becomes a Tier 2 memory)
        await compact_interaction(agent_id, oldest, "conversation_segment")

        # Keep only the newest 10 in the active buffer
        buffer = buffer[10:]

    return buffer
```

This creates a rolling window where recent conversation is always in full detail, and older conversation is available through recall memory with optional full-transcript retrieval.
