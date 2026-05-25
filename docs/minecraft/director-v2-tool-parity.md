# Director V2 Tool Parity Inventory

This inventory mirrors `TOOL_PARITY` in
`core/minecraft/director/tool_parity.py`. It covers every concrete backend
`BaseTool` in `tools/`, plus the journal image generator in
`tools/journal_image_tool.py`.

## Classifications

- `callable_now`: Director V2 may execute the backend tool through the typed adapter.
- `approval_gated`: Director V2 may only queue, hold, or route the request through an existing review path.
- `deferred`: Valid capability, but owned by a tracked future issue.
- `retired`: Old capability no longer belongs in Minecraft Director V2.
- `replaced_by_minecraft`: Old backend view/action replaced by Minecraft-native perception or action.

## Cross-Issue Boundaries

- Code execution remains deferred to #560.
- Memory tools remain callable while the bridge and memory parity work from #551, #552, and #708 continues.
- Journal image generation remains deferred to #583.
- `generate_tilemap` is retired with the tilemap removal work in #619.
- `get_world_state` is replaced by Minecraft perception and the shared world/task blackboard work in #712.
- Distress/rescue behavior is separate #713 work, not a tool parity reimplementation.
- Build feedback is separate #714 work, not the old tilemap generator.

## Parity Table

| Tool | Module | Category | Classification | Linked issue | Minecraft replacement | Rationale |
| --- | --- | --- | --- | --- | --- | --- |
| `check_email_responses` | `tools.revenue_tools` | email | `callable_now` | N/A | N/A | Email response lookup is read-only and does not send external communication. |
| `check_post_performance` | `tools.revenue_tools` | social | `callable_now` | N/A | N/A | Engagement lookup is read-only and does not publish external content. |
| `create_poll` | `tools.audience_tools` | audience | `approval_gated` | N/A | N/A | Audience polls are public interaction requests and need explicit approval in Director V2. |
| `dispatch_alpha` | `tools.alpha_dispatch` | alpha | `callable_now` | N/A | N/A | Alpha errands already route through the backend bridge, kill switch, and LLM client. |
| `draft_email` | `tools.revenue_tools` | email | `approval_gated` | N/A | N/A | Outbound email stays human-review-only via the existing draft artifact path. |
| `draft_social_post` | `tools.revenue_tools` | social | `approval_gated` | N/A | N/A | Social publishing stays human-review-only via the existing draft artifact path. |
| `execute_code` | `tools.code_execution` | code | `deferred` | #560 | N/A | Embodied code execution needs the dedicated bridge and sandbox exposure work. |
| `fetch_url` | `tools.web_tools` | web | `callable_now` | N/A | N/A | URL fetch remains a typed backend tool with SSRF checks and cost tracking. |
| `generate_journal_image` | `tools.journal_image_tool` | journal_image | `deferred` | #583 | N/A | Journal illustration generation remains valid but is owned by the journal-image preservation work. |
| `generate_tilemap` | `tools.tilemap_gen` | tilemap | `retired` | #619 | Minecraft build macros and planner scheduling. | Phaser tilemap generation is superseded by Minecraft build planning and removal work. |
| `get_audience_status` | `tools.audience` | audience | `callable_now` | N/A | N/A | Read-only audience snapshot remains useful context for Minecraft scenes. |
| `get_poll_results` | `tools.audience_tools` | audience | `callable_now` | N/A | N/A | Poll result reads are internal context and do not publish anything. |
| `get_revenue_status` | `tools.revenue_tools` | revenue | `callable_now` | N/A | N/A | Read-only financial health context remains valid for Sentinel and Vera. |
| `get_world_state` | `tools.world_state` | world_state | `replaced_by_minecraft` | #712 | Minecraft perception snapshot plus shared world/task blackboard. | The old Redis world snapshot is superseded by Minecraft perception and shared scene state. |
| `leave_alliance` | `tools.social_tools` | alliance | `callable_now` | N/A | N/A | Leaving an alliance is internal state managed by the existing alliance manager. |
| `manage_task` | `tools.task_management` | task | `callable_now` | #712 | N/A | The shared task board remains useful until the Minecraft blackboard is expanded. |
| `propose_alliance` | `tools.social_tools` | alliance | `callable_now` | N/A | N/A | Alliance proposals are internal social governance and use the existing manager. |
| `propose_build` | `tools.build_tools` | world_state | `callable_now` | #855 | N/A | Structured BuildIntent submission is the first-class signal for building; Director V2 routes it to the build macro scheduler. |
| `propose_character` | `tools.character_tools` | character | `callable_now` | N/A | N/A | Character applications stay internal and still flow through the existing voting lifecycle. |
| `propose_self_modification` | `tools.self_modification` | self_mod | `approval_gated` | N/A | N/A | Self-modification only creates a human-review proposal and must not auto-apply changes. |
| `recall_memory` | `tools.memory_tools` | memory | `callable_now` | #551/#552/#708 | N/A | Tier 2 recall is still a backend memory read and keeps the three-tier memory boundary. |
| `retrieve_transcript` | `tools.memory_tools` | memory | `callable_now` | #551/#552/#708 | N/A | Tier 3 transcript lookup remains a read-only backend memory operation. |
| `send_chat_message` | `tools.audience_tools` | audience | `approval_gated` | N/A | N/A | Public chat output must not bypass Management or the human approval policy. |
| `send_message` | `tools.messaging` | messaging | `callable_now` | N/A | N/A | Internal agent messaging is not public external communication and remains event-bus backed. |
| `transfer_budget` | `tools.economy_tools` | economy | `callable_now` | N/A | N/A | Internal agent-to-agent budget transfers preserve the existing economy manager boundary. |
| `update_core_memory` | `tools.memory_tools` | memory | `callable_now` | #551/#552/#708 | N/A | Tier 1 core writes preserve existing section and cross-agent writer checks. |
| `view_account` | `tools.economy_tools` | economy | `callable_now` | N/A | N/A | Account balance reads are internal context for budgeting scenes. |
| `view_alliances` | `tools.social_tools` | alliance | `callable_now` | N/A | N/A | Alliance listing is a read-only internal governance lookup. |
| `view_evolution_log` | `tools.self_modification` | self_mod | `callable_now` | N/A | N/A | Evolution log reads are internal and preserve the existing self-modification audit trail. |
| `vote_alliance` | `tools.social_tools` | alliance | `callable_now` | N/A | N/A | Alliance votes are internal governance actions with existing validation. |
| `vote_character` | `tools.character_tools` | character | `callable_now` | N/A | N/A | Character votes are internal governance actions with existing validation. |
| `web_search` | `tools.web_tools` | web | `callable_now` | N/A | N/A | Search remains a typed backend tool with rate limiting and cost tracking. |
