# Human Tasks Checklist

Things Brad must do personally — can't be delegated to AI or automated.

---

## Before development starts (Week 0)

### Accounts to create
- [ ] **Hetzner account** — https://accounts.hetzner.com/signUp — order AX102 server (allow 1-3 days provisioning)
- [ ] **OpenRouter account** — https://openrouter.ai — add $50 initial credits
- [ ] **PixelLab account** — https://www.pixellab.ai — create account, add credits
- [ ] **Twitch account** — claim channel name "LivestreamToAGI" (or preferred name)
- [ ] **YouTube channel** — create channel with same branding
- [ ] **Restream.io account** — free tier, connect Twitch + YouTube
- [ ] **Discord server** — create server, set up channels (see structure in implementation plan)
- [ ] **GitHub repo** — create `livestream-to-agi` repo, public
- [ ] **Twitter/X account** — create @LivestreamToAGI (or preferred handle)
- [ ] **TikTok account** — for Daily Brief clips
- [ ] **Vercel account** — for Next.js website deployment
- [ ] **Domain name** — register livestreamtoagi.com (or preferred)
- [ ] **Eklipse account** — https://eklipse.gg — for auto-clipping (free tier)
- [ ] **Ko-fi account** — https://ko-fi.com — for donations (0% platform fee)

### API keys to obtain
- [ ] **OpenRouter API key** — Settings → API Keys
- [ ] **Twitch developer app** — https://dev.twitch.tv/console — create app, get Client ID + OAuth token
- [ ] **Twitch bot OAuth token** — generate at https://twitchapps.com/tmi/
- [ ] **YouTube API key** — Google Cloud Console → YouTube Data API v3
- [ ] **PixelLab API key** — from PixelLab dashboard

### Financial setup
- [ ] **Budget:** Save $4,000-5,000 before launch
- [ ] **LLC formation** (recommended, not required at MVP): consult lawyer or use service like Stripe Atlas
- [ ] **Stripe account** — for donation payment links (optional, Ko-fi works for MVP)

### Legal (do before public launch)
- [ ] **Read Twitch TOS** and save as `twitch_tos.md` for Overseer context
- [ ] **Read YouTube community guidelines** and save as `youtube_tos.md`
- [ ] **Consult a lawyer** about liability for AI-generated livestream content (30-min consultation, ~$150-300)
- [ ] **Create content_rules.yaml** — your custom rules beyond platform TOS (no politics, no specific public figures, etc.)

### Creative decisions (make before development)
- [ ] **Choose final agent names** — current: Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok
- [ ] **Choose community name** — or decide to let community vote
- [ ] **Write the whiteboard message** — the "spark of life" text agents see when they wake up
- [ ] **Prepare 10 seed challenges** — tasks for Challenge Hour when audience is small
- [ ] **Decide stream schedule** — recommended: 12hr/day initially, which 12 hours?
- [ ] **Decide Alpha Agent product URL** — where do viewers go for their own Alpha?

---

## During development (Weeks 1-4)

### Week 1
- [ ] **SSH into Hetzner server** and verify Claude Code / your engineer can access it
- [ ] **Test OpenRouter** — verify all models respond (Claude, GPT, Gemini, Grok, DeepSeek)
- [ ] **Listen to Edge TTS voices** — verify each agent's voice sounds right for their character
- [ ] **Read and review agent conversations** — are they entertaining? Give feedback to tune prompts
- [ ] **Approve/reject any system prompt changes** during tuning

### Week 2
- [ ] **Purchase pixel art tileset** from itch.io (office interior, ~$10-20)
- [ ] **Generate character sprites** using PixelLab prompts (from CHARACTER-SHEETS.md)
- [ ] **Review sprite quality** — do they look good? Consistent style?
- [ ] **Watch test stream privately** — is it watchable? What's boring? What works?
- [ ] **Test Edge TTS voices** on actual agent dialogue — any that sound wrong?

### Week 3
- [ ] **Set up Twitch channel** — profile image, banner, description, category
- [ ] **Set up YouTube channel** — same branding
- [ ] **Configure Restream** — connect both channels
- [ ] **Set up Discord** — invite link, welcome message, channel descriptions
- [ ] **Test kill switch from phone** — verify you can mute agents in an emergency
- [ ] **Invite 10-20 friends** to test Twitch chat commands
- [ ] **Review all agent outputs** over 24 hours — anything concerning for TOS?

### Week 4
- [ ] **Review world expansion pipeline** — does the output look good?
- [ ] **Write launch tweet thread** (or have Aurora draft it for your review)
- [ ] **Write Reddit posts** for r/artificial, r/LocalLLaMA, r/Twitch, r/LivestreamFail
- [ ] **Prepare Hacker News submission**
- [ ] **Record yourself explaining the project** for a 60-second intro video (optional but helps)

---

## Launch and ongoing (Weeks 5+)

### Soft launch (Week 5)
- [ ] **Stream to unlisted YouTube** — share link with friends only
- [ ] **Monitor costs obsessively** — check Langfuse and OpenRouter dashboard every few hours
- [ ] **Collect feedback** — what's funny, what's boring, what breaks
- [ ] **Be available for emergency kills** — keep phone nearby for first 72 hours

### Public launch (Week 6)
- [ ] **Post launch content** on Twitter, Reddit, HN, Discord
- [ ] **Monitor stream** for first 48 hours — be ready to kill switch
- [ ] **Engage with early viewers** in Discord
- [ ] **Review and approve** any agent-drafted social media posts or emails

### Ongoing weekly tasks
- [ ] **Review self-modification proposals** (until auto-approval is enabled ~month 3)
- [ ] **Review social media drafts** (until auto-posting is enabled ~month 3+)
- [ ] **Check weekly costs** in Langfuse/OpenRouter
- [ ] **Read agent journals** — are personalities holding? Anything drifting?
- [ ] **Check Overseer intervention log** — is it catching everything? Too aggressive? Too lenient?
- [ ] **Engage with Discord community** — at least a few times per week
- [ ] **Review grant applications** before agents submit them

### Monthly tasks
- [ ] **Review and adjust CostGovernor limits** based on actual usage
- [ ] **Review content_rules.yaml** — add any new rules based on issues encountered
- [ ] **Assess audience growth** — is the content working? What needs to change?
- [ ] **Plan seasonal events** (elections, themed weeks, guest agents)
- [ ] **Evaluate: should auto-approval be enabled yet?** (target: month 3)
