# Research Paper Index — Livestream to AGI

> **Purpose:** This index maps every paper in `research/` to the project systems it informs. When working on a subsystem (memory, conversation engine, agent personality, evaluation, etc.), consult the relevant papers listed here for context, prior art, and testable hypotheses.
>
> **Last updated:** 2026-04-15

---

## Quick Lookup by Project System

| System | Papers (short key) |
|--------|-------------------|
| **Memory (core/recall/archival)** | A-Mem, Mem0, MemGPT, Generative Agents |
| **Conversation Engine & Speaker Selection** | Who Speaks Next, CAMEL, Multi-Agent Collab Survey |
| **Agent Personality & Identity** | Entropy (Emergence), Dynamic Personality, Value Diversity, Personas Evolved |
| **Proactivity & Autonomy** | D2A (Desire-Driven), VOYAGER |
| **Social Dynamics & Relationships** | AgentSociety, Value Diversity, SOTOPIA, Entropy (Emergence) |
| **Evaluation Framework** | SOTOPIA, MultiAgentBench, AgentSociety |
| **Agent Collaboration & Architecture** | MetaGPT, CAMEL, Multi-Agent Collab Survey, MultiAgentBench |
| **Safety & Ethics** | Personas Evolved, AgentSociety |
| **Economic Behavior** | AgentSociety, D2A |
| **Audience Interaction (novel — no direct prior art)** | SOTOPIA (closest: human-in-the-loop eval), AgentSociety (external shocks) |

---

## Full Paper Index

### 1. Generative Agents: Interactive Simulacra of Human Behavior
- **File:** `generative-agents-2304.03442v2.pdf`
- **Authors:** Park, O'Brien, Cai, Morris, Liang, Bernstein (Stanford / Google)
- **Venue:** UIST 2023
- **arXiv:** 2304.03442
- **Summary:** Introduces 25 generative agents in a Sims-like sandbox ("Smallville"). Agents observe, reflect, and plan using a 3-tier memory architecture (observation stream, reflection, planning). Demonstrates emergent social behaviors — information diffusion, relationship formation, coordinated group activities — from simple initial conditions. Ablation shows all three memory components (observation, reflection, planning) are critical for believability.
- **Relevance to project:**
  - **Memory system:** Direct ancestor of our core/recall/archival architecture. Our 3-tier design maps almost 1:1 to their observation/reflection/planning tiers.
  - **Agent personality:** Their agents have minimal initial personality (one paragraph backstory). Our heavy personality seeding is a deliberate divergence worth testing experimentally.
  - **World design:** Their pixel-art sandbox world with spatial proximity influencing interaction is architecturally similar to our Phaser.js frontend.
  - **Key experiment to run:** Compare our seeded agents against Park-style minimal-backstory agents from the same simulation snapshot.

---

### 2. MemGPT: Towards LLMs as Operating Systems
- **File:** `memgpt-2310.08560v2.pdf`
- **Authors:** Packer, Wooders, Lin, Fang, Patil, Stoica, Gonzalez (UC Berkeley)
- **Venue:** Preprint, February 2024
- **arXiv:** 2310.08560
- **Summary:** Treats the LLM context window as an operating system's main memory, with function calls to page information between working context, recall storage, and archival storage. Achieves 93.4% accuracy on deep memory retrieval tasks vs. 35.3% baseline. Key insight: agents should *actively manage* their own memory via function calls rather than relying on passive retrieval.
- **Relevance to project:**
  - **Memory system:** Our recall memory uses passive embedding similarity; MemGPT's active paging is more sophisticated. Consider giving agents explicit `page_in_memory` and `archive_memory` tool calls.
  - **Token management:** Their queue manager and recursive summarization approach is relevant to our `compaction.py` module.
  - **Long conversations:** Their multi-session chat experiments directly apply to our 24/7 persistent agents.

---

### 3. A-Mem: Agentic Memory for LLM Agents
- **File:** `a-mem-agentic-memory-2502.12110v11.pdf`
- **Authors:** Xu, Liang, Mei, Gao, Tan, Zhang (Rutgers / AIOS Foundation)
- **Venue:** Preprint, 2025
- **arXiv:** 2502.12110
- **Summary:** Zettelkasten-inspired memory system where memories are structured as interconnected atomic notes with keywords, tags, contextual descriptions, and cross-links. When new memories arrive, the system autonomously generates links to related memories AND evolves existing memories by updating their context. Outperforms MemGPT, MemoryBank, and ReadAgent across six evaluation metrics.
- **Relevance to project:**
  - **Memory system (HIGH PRIORITY):** Our recall memory is flat embedding similarity. A-Mem's approach would make agent memories interconnected and self-evolving — critical for weeks/months of continuous operation.
  - **Reflection cycles:** Their memory evolution mechanism could replace or augment our 6-hour reflection cycles with continuous, incremental memory refinement.
  - **Implementation path:** Their note construction (content + keywords + tags + contextual description + links) maps well to our PostgreSQL + pgvector schema. Would require adding a `memory_links` table and modifying the recall retrieval to follow link chains.

---

### 4. Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory
- **File:** `mem0-scalable-long-term-memory-2504.19413v1.pdf`
- **Authors:** Chhikara, Khant, Aryan, Singh, Yadav (Mem0.ai)
- **Venue:** Preprint, April 2025
- **arXiv:** 2504.19413
- **Summary:** Production-focused memory architecture with two variants: Mem0 (extraction + update pipeline for facts) and Mem0^G (graph-based with entity nodes, relationship edges, and semantic labels). Achieves 26% improvement over OpenAI's memory on LLM-as-judge metrics. Key features: incremental processing, conflict detection, 91% lower p95 latency vs. full-context approaches, 90%+ token cost savings.
- **Relevance to project:**
  - **Memory system:** Their Mem0^G graph variant is relevant if we want to track entity relationships explicitly (agent-to-agent trust, project ownership, alliance membership) beyond what embedding similarity captures.
  - **Scaling:** If we expand beyond 9 agents or open the sandbox to external simulations, their production optimizations (latency, cost) become important.
  - **Conflict resolution:** Their ADD/UPDATE/DELETE/NOOP memory operations could improve how our reflection cycles handle contradictory memories.

---

### 5. CAMEL: Communicative Agents for "Mind" Exploration of Large Language Model Society
- **File:** `CAMEL-comms-for-agent-society-2303.17760v2.pdf`
- **Authors:** Li, Hammoud, Itani, Khizbullin, Ghanem (KAUST)
- **Venue:** NeurIPS 2023
- **arXiv:** 2303.17760
- **Summary:** Introduces "inception prompting" — a role-playing framework where an AI User and AI Assistant collaborate autonomously to complete tasks. Identifies key failure modes: role flipping, assistant repeating instructions, flake replies, infinite loops. Generates datasets (AI Society, Code) for studying cooperative agent behavior. Also introduces a "Misalignment" dataset demonstrating risks of unguided agent systems.
- **Relevance to project:**
  - **Conversation engine:** Our weighted speaker selection is a deliberate departure from CAMEL's rigid role assignment. Our approach is more suitable for social simulation vs. task completion.
  - **Failure modes:** Their catalog of degeneration patterns (role flipping, infinite loops, flake replies) is a useful checklist for our conversation engine's health monitoring.
  - **Safety:** Their Misalignment dataset findings reinforce why our Management content filter exists. Consider testing whether our filter catches the failure modes they identified.

---

### 6. MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework
- **File:** `meta-progr-multi-agent-collab-2308.00352v7.pdf`
- **Authors:** Hong, Zhuge, Chen, Zheng, Cheng, Zhang, Wang, Yau, Lin, Zhou, Ran, Xiao, Wu, Schmidhuber (DeepWisdom / KAUST / multiple universities)
- **Venue:** ICLR 2024
- **arXiv:** 2308.00352
- **Summary:** Encodes human Standardized Operating Procedures (SOPs) into multi-agent workflows. Agents have specialized roles (Product Manager, Architect, Engineer, QA) and communicate through structured artifacts (PRDs, design docs, code) rather than free-form chat. Achieves 100% task completion on software engineering benchmarks. Key insight: structured intermediate outputs between agents dramatically reduce cascading hallucinations.
- **Relevance to project:**
  - **Agent collaboration:** Our agents communicate in free-form natural language. MetaGPT's insight about structured artifacts suggests we should consider having agents share explicit goal states, project status documents, or task boards — not just conversation.
  - **Role specialization:** Their role-based approach validates our agent archetype design (Rex=Engineer, Aurora=Creative, Sentinel=QA), though our roles are personality-driven rather than workflow-driven.
  - **Code execution:** Their executable feedback mechanism (code runs, errors feed back into prompts) is directly relevant to our coding sandbox tool.

---

### 7. VOYAGER: An Open-Ended Embodied Agent with Large Language Models
- **File:** `voyager-minecraft-2305.16291v2.pdf`
- **Authors:** Wang, Xie, Jiang, Mandlekar, Xiao, Zhu, Fan, Anandkumar (NVIDIA / Caltech / UT Austin / Stanford / UW Madison)
- **Venue:** Preprint, October 2023
- **arXiv:** 2305.16291
- **Summary:** First LLM-powered lifelong learning agent in Minecraft. Three components: automatic curriculum (GPT-4 proposes progressively harder tasks), skill library (executable code stored and retrieved by embedding), iterative prompting (environment feedback + execution errors + self-verification). Obtains 3.3x more unique items and unlocks tech tree 15.3x faster than baselines. Skills are compositional and transferable to new worlds.
- **Relevance to project:**
  - **Goal system:** VOYAGER's automatic curriculum is what our goal generation system aspires to be. Critical gap: VOYAGER verifies task completion against environment feedback; our agents generate goals but don't robustly verify achievement.
  - **Skill library:** Their embedding-indexed code library pattern could apply to our agents' learned behaviors — storing successful strategies and retrieving them in similar situations.
  - **Self-verification:** The biggest takeaway. We need agents that check whether their actions actually worked, not just propose actions. This connects to the D2A framework.

---

### 8. D2A: Simulating Human-like Daily Activities with Desire-Driven Autonomy
- **File:** `simulating-human-like-activities-desire-driven-autonomy-2412.06435v3.pdf`
- **Authors:** Wang, Chen, Zhong, Ma, Wang (Peking University / HKU / Beijing Normal University)
- **Venue:** ICLR 2025
- **arXiv:** 2412.06435
- **Summary:** Replaces instruction-driven or reward-driven agent behavior with a desire-driven Value System inspired by Maslow's hierarchy. Agents have 11 desire dimensions (hunger, thirst, sleepiness, social connectivity, joy, passion, spiritual satisfaction, etc.) that decay over time. At each step, agents: (1) describe current desire states qualitatively, (2) propose candidate activities, (3) evaluate each activity against current needs, (4) select the best-aligned activity. Produces 25% higher coherence scores over 50+ time steps vs. baselines (ReAct, BabyAGI, LLMob).
- **Relevance to project (HIGH PRIORITY):**
  - **Proactivity system:** Direct replacement for our idle-timeout trigger system. We already track internal states (frustration, boredom, social_need, creative_need, energy, satisfaction). D2A shows how to wire these into a decision loop instead of just using them for dream triggers.
  - **Implementation path:** Map our 6 internal states to D2A's desire dimensions. Add a `propose_activities` step before each agent action. Score activities against current state. This is the "single highest-impact change" recommended in our research analysis.
  - **Evaluation:** Their evaluation framework (naturalness, coherence, plausibility via GPT-4o and human annotators) can supplement our 13-category eval.

---

### 9. AgentSociety: Large-Scale Simulation of LLM-Driven Generative Agents
- **File:** `agent-society-2502.08691v1.pdf`
- **Authors:** Piao, Yan, Zhang, Li, Yan, Lan, Lu, Zheng, Wang, Zhou, Gao, Xu, Zhang, Rong, Su, Li (Tsinghua University)
- **Venue:** Preprint, February 2025
- **arXiv:** 2502.08691
- **Summary:** Comprehensive social simulator with 10K+ agents across realistic urban, social, and economic environments. Agents have psychology-grounded "minds" (emotions, needs, motivations) that drive behaviors through mind-behavior coupling. Simulates 5M+ interactions. Successfully reproduces real-world social phenomena: polarization, inflammatory message spread, effects of universal basic income, hurricane impact. Uses MQTT for high-performance distributed simulation.
- **Relevance to project:**
  - **Social dynamics:** Their mind-behavior coupling architecture (emotions/needs drive actions) validates and extends our internal state tracking. They integrate established social science theories (Maslow, Theory of Planned Behavior) more formally than we do.
  - **Evaluation methodology:** Their four social experiments (polarization, misinformation, UBI, external shocks) provide templates for our own experiments. Their evaluation framework assesses both individual agent behaviors and emergent collective phenomena.
  - **Scale considerations:** Their MQTT-based distributed architecture is relevant if we scale beyond 9 agents or want to run many parallel experiment forks.
  - **Economic simulation:** Their economic environment models are more sophisticated than ours, though ours has the unique advantage of *real* money.

---

### 10. SOTOPIA: Interactive Evaluation for Social Intelligence in Language Agents
- **File:** `interactive-eval-agents-2310.11667v2.pdf`
- **Authors:** Zhou, Zhu, Mathur, Zhang, Qi, Yu, Bisk, Fried, Neubig, Sap (CMU)
- **Venue:** ICLR 2024
- **arXiv:** 2310.11667
- **Summary:** Open-ended social interaction environment with 90 scenarios, 40 characters, and 90 relationships. Evaluates agents across 7 dimensions: Goal Completion, Believability, Knowledge, Secret-keeping, Relationship impact, Social Rules, Financial outcomes. Finds GPT-4 achieves significantly lower goal completion than humans on hard scenarios and struggles with strategic social communication. LLM judges correlate with human judges on most dimensions but weaken on nuanced tasks.
- **Relevance to project:**
  - **Evaluation framework:** Their 7 evaluation dimensions directly informed our 13-category eval. Their finding that LLM-as-judge works for most dimensions but weakens on nuance validates our plan to supplement with human evaluation.
  - **Character design:** Their character profile structure (personality traits, moral values, decision-making style, relationships) is more psychologically grounded than our YAML configs. Consider enriching our agent configs with Schwartz values and decision-making style.
  - **Scenario design:** Their task space (cooperative, competitive, mixed-motive scenarios) could template our simulation seed files.

---

### 11. Spontaneous Emergence of Agent Individuality Through Social Interactions in LLM-Based Communities
- **File:** `entropy-26-01092.pdf`
- **Authors:** Takata, Masumori, Ikegami (University of Tokyo)
- **Venue:** MDPI Entropy, December 2024
- **DOI:** 10.3390/e26121092
- **Summary:** Starts with 10 completely homogeneous LLM agents (Llama 2, no personality, no memories, no roles) in a 50x50 grid. Agents message neighbors, store situational summaries, and move. Key findings: (1) agents naturally differentiate behavior, emotions, and MBTI-measurable personality types through interaction alone, (2) agents spontaneously generate shared hallucinations and cultural artifacts (e.g., "trees" concept spreads spatially), (3) differentiation varies with spatial scale and interaction density.
- **Relevance to project (HIGH PRIORITY):**
  - **Personality seeding experiment:** This is the primary reference for our planned organic emergence experiment. Their methodology (homogeneous start, measure differentiation over time) is directly replicable in our system.
  - **Baseline design:** Use their approach as our control condition — agents with minimal identity in the same world, same duration, same evaluation framework.
  - **Cultural emergence:** Their finding that agents spontaneously create shared cultural artifacts (hallucinations as proto-culture) is fascinating and testable in our system. Do our heavily-seeded agents create *less* organic culture because their identities are pre-defined?
  - **Spatial dynamics:** Their spatial scale findings are relevant to our proximity-based conversation grouping system.

---

### 12. Dynamic Personality in LLM Agents: A Framework for Evolutionary Modeling and Behavioral Analysis in the Prisoner's Dilemma
- **File:** `dynamic-personality-in-llm-agents-evolutionary-models-behavior-analysis-2025.findings-acl.1185.pdf`
- **Authors:** Zeng, Wang, Zhao, Qu, He, Hou, Hu (Tianjin University / CHEARI)
- **Venue:** ACL 2025 Findings
- **Summary:** Tests dynamic personality evolution using the Prisoner's Dilemma as a socially significant scenario. Agents undergo random mutation (subtle personality description changes) and natural selection (higher-payoff agents survive). Key findings: (1) personality converges — agents tend toward extreme collaboration or defection, (2) the dominant effect appears in a single round while adaptation accumulates over time, (3) BFI (Big Five) personality metrics predictably correlate with behavioral patterns.
- **Relevance to project:**
  - **Adaptive personality:** Direct support for making our personality parameters (chattiness, initiative, etc.) adaptive rather than static. Their mutation + selection mechanism could inspire our reflection-cycle personality adjustments.
  - **Bounded adaptation:** Their approach of small, successive mutations with selection pressure is a good model for our proposed ±0.1 personality parameter shifts per reflection cycle.
  - **Measurement:** Their use of BFI metrics to track personality evolution provides a measurement framework we can adopt for longitudinal personality tracking across seasons.

---

### 13. Who Speaks Next? Multi-party AI Discussion Leveraging the Systematics of Turn-Taking in Murder Mystery Games
- **File:** `who-speaks-next-ai-discussions-frai-8-1582287.pdf`
- **Authors:** Nonomura, Mori (Utsunomiya University)
- **Venue:** Frontiers in Artificial Intelligence, June 2025
- **DOI:** 10.3389/frai.2025.1582287
- **Summary:** Studies multi-party turn-taking in Murder Mystery games using conversation analysis theory. Implements two mechanisms: "Self-Selection" (agents bid to speak based on importance values) and "Current Speaker Selects Next" (the speaking agent designates the next speaker). Uses 3-tier memory (History, shortTermHistory, longTermHistory). Finds that implementing turn-taking systematics significantly reduces dialogue breakdowns and improves information sharing and logical reasoning.
- **Relevance to project:**
  - **Conversation engine (HIGH PRIORITY):** Directly validates our weighted speaker selection approach. Their "Self-Selection" mechanism (agents express desire/importance to speak) maps to our 5-factor weighted selection. Their "Current Speaker Selects Next" could be added as a 6th factor — explicit addressing.
  - **Emotional activation:** Their `think()` function where agents generate an importance value (0-9) for wanting to speak could inform the emotional_activation factor recommended in our research analysis.
  - **Dialogue quality:** Their evaluation criteria (information sharing effectiveness, logical reasoning) complement our conversation quality eval categories.

---

### 14. Multi-Agent Collaboration Mechanisms: A Survey of LLMs
- **File:** `multi-agent-collaboration-mechanisms-2501.06322v1.pdf`
- **Authors:** Tran, Dao, Nguyen, Pham, O'Sullivan, Nguyen (University College Cork / Pusan National University / Trinity College Dublin)
- **Venue:** Preprint, January 2025
- **arXiv:** 2501.06322
- **Summary:** Comprehensive survey characterizing multi-agent collaboration across five dimensions: actors (agents involved), types (cooperation, competition, coopetition), structures (peer-to-peer, centralized, distributed), strategies (role-based, rule-based, model-based), and coordination protocols. Covers real-world applications across 5G/6G, Industry 5.0, question answering, and social/cultural settings. Identifies open challenges including collective reasoning, decision-making, and paths toward artificial collective intelligence.
- **Relevance to project:**
  - **Architecture positioning:** Use this survey to position our system in the taxonomy. Our architecture is: peer-to-peer structure, role-based strategy (personality archetypes), with a centralized safety layer (Management). This hybrid is unusual in the literature.
  - **Collaboration types:** Our agents exhibit all three types (cooperation on projects, competition for budget, coopetition in conversations). Most systems in the survey only handle one.
  - **Literature review:** Essential reference for any paper we write. Provides the landscape against which our contributions should be framed.

---

### 15. MultiAgentBench: Evaluating the Collaboration and Competition of LLM Agents
- **File:** `multi-agent-bench-colab-competition-agents-2503.01935v1.pdf`
- **Authors:** Zhu, Du, Hong, Yang, Guo, Wang, Qian, Tang, Ji, You (UIUC)
- **Venue:** Preprint, March 2025
- **arXiv:** 2503.01935
- **Summary:** Comprehensive benchmark (MARBLE framework) for multi-agent systems across task-oriented and social-simulation scenarios. Introduces milestone-based KPIs and Key Performance Indicators that track both task completion and coordination quality. Tests coordination protocols (star, chain, tree, graph) and planning strategies (vanilla, CoT, group discussion, cognitive evolving). Finds graph structure and cognitive planning improve milestone achievement by 3%.
- **Relevance to project:**
  - **Evaluation framework:** Their milestone-based KPIs could strengthen our eval. Instead of only scoring conversation quality post-hoc, track whether agents hit intermediate milestones in their projects/goals.
  - **Coordination protocols:** Their comparison of star/chain/tree/graph topologies is relevant if we experiment with different communication structures (e.g., Vera as centralized coordinator vs. fully decentralized conversation).
  - **Cognitive evolving planning:** Their method of generating expectations, comparing against results, and updating plans mirrors what our reflection cycles should produce.

---

### 16. On the Dynamics of Multi-Agent LLM Communities Driven by Value Diversity
- **File:** `multi-agent-llm-communities-driven-by-value-diversity-2512.10665v1.pdf`
- **Authors:** Huang, Zhao, Yi, Xie (Stanford / Microsoft Research Asia)
- **Venue:** Working paper, December 2025
- **arXiv:** 2512.10665
- **Summary:** Studies how value diversity (grounded in Schwartz's Theory of Basic Human Values) shapes collective behavior in LLM communities. Uses naturalistic value elicitation (agents discover values through ethical dilemmas, not assignment). Tests group sizes of 4, 10, and 30 with varying value composition (homogeneous, diverse, no-value control). Three-stage protocol: free-form interaction, governance emergence (agents propose rules), collaborative rule formation (agents draft a constitution). Key findings: value diversity enhances stability and fosters emergent behaviors, but extreme heterogeneity induces instability.
- **Relevance to project:**
  - **Multi-model diversity:** Our agents run on 6 different LLM providers, creating *natural* value diversity (different training data, different RLHF, different reasoning styles). This paper provides the theoretical framework for studying what our multi-model setup produces.
  - **Governance emergence:** Their Stage 2 (agents propose governance rules) is directly relevant to our Season 4+ plans for inter-agent governance and economic decision-making.
  - **Group dynamics:** Their finding that moderate diversity outperforms both homogeneity and extreme heterogeneity has implications for how we design agent rosters for experiments.
  - **Persona creation via dilemmas:** Their approach of generating personas through ethical dilemmas rather than direct assignment could be an alternative to our YAML personality configs.

---

### 17. Personas Evolved: Designing Ethical LLM-Based Conversational Agent Personalities
- **File:** `personas-evolved-designing-ethical-llm-2502.20513v1.pdf`
- **Authors:** Desai, Dubiel, Zargham, Mildner, Spillner (Northeastern / U. Luxembourg / U. Bremen)
- **Venue:** Workshop proposal, ACM 2025
- **arXiv:** 2502.20513
- **Summary:** Workshop proposal addressing the ethical dimensions of LLM-based persona design. Highlights concerns about bias, manipulation, unintended emotional attachments, and the gap between CUI (Conversational User Interface) design practices and the new dynamics introduced by LLMs generating responses from training data. Aims to establish shared vocabulary (persona vs. agent vs. character) and develop ethical guidelines.
- **Relevance to project:**
  - **Safety & transparency:** Directly relevant to our content filter and safety commitments. Their concerns about emotional attachment and manipulation are pertinent given our audience-facing, personality-rich agents.
  - **Ethical framework:** Useful reference for framing the ethical considerations in any paper we publish. Our radical transparency commitment and human-approval requirements for external comms address many of their concerns.
  - **Terminology:** Their push for consistent vocabulary (persona/agent/character distinction) should inform how we describe our agents in publications.

---

## Papers Referenced in Analysis But Not in Collection

These papers are cited in `RESEARCH-ANALYSIS-2026.md` but their PDFs are not in the `research/` folder. Consider downloading for reference:

| Paper | Why It Matters | Where to Find |
|-------|---------------|---------------|
| OpenClaw Dreaming Guide (2026) | 3-phase sleep architecture (Light/REM/Deep) for memory consolidation | dev.to article |
| "Let Them Sleep" (2025) | Sleep cycles updating behavioral tendencies, not just adding journals | Search arXiv |
| Emergent Coordination in Multi-Agent Language Models (2025) | Information-theoretic framework for measuring genuine higher-order structure | arXiv 2510.05174 |
| Validation is the Central Challenge for Generative Social Simulation (PMC 2025) | Critical review of validation methodology for social simulations | PMC |
| Structured Personality Control and Adaptation (2025) | Jungian framework for personality seeding via cognitive function preferences | arXiv 2601.10025 |

---

## How to Use This Index

**When building or modifying a system:**
1. Look up the system in the "Quick Lookup" table above
2. Read the relevant paper summaries and "Relevance to project" sections
3. Check the paper itself for implementation details, evaluation methodology, or experimental design

**When designing an experiment:**
1. Check if a paper already tested something similar
2. Use their methodology as a starting point (especially evaluation metrics)
3. Note where our system diverges — those divergences are often the most publishable findings

**When writing a paper or blog post:**
1. Cite the papers that informed the system under discussion
2. Frame your contribution relative to the closest prior work
3. Use the "Relevance" notes to articulate how your approach differs and why
