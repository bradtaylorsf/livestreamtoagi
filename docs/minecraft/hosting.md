# Hosting the Server 24/7 — Decide & Document (local vs cloud)

A running-on-your-laptop server (that's [server-setup.md](./server-setup.md))
is fine to learn on, but the show is **24/7**: the world has to stay up when
your laptop is closed. This doc decides **where** the durable server lives,
gives one concrete recommendation with a real spec and a monthly cost, and
shows the tradeoffs so the decision is auditable. No prior ops experience
assumed.

> **Issue:** E2-3 (epic E2). **Decides:** the host for a 24/7 Minecraft
> server. **Builds on:** E2-1 ([server-setup.md](./server-setup.md)) for the
> server itself and E1-R1 (`docs/decisions/0001-minecraft-version-and-server.md`)
> for sizing. **Ties to:** E1-R6 (`docs/decisions/0006-video-capture.md`) —
> the production *capture* host is a separate, heavier machine; see
> [§ Co-location with the capture host](#co-location-with-the-capture-host-e1-r6).

## Non-technical summary

The Minecraft server is a small, headless program. It does **not** need a
graphics card and it does **not** need a powerful machine — it needs to be
**always on and reliable**. The cheapest reliable option is a small cloud
Linux server ("VPS") for **roughly $15–25 a month**. If you already own a
computer that can be left running 24/7, that costs even less and is a fine
choice — the only catch is that the show goes down when your home power or
internet does.

The expensive machine in this project (a GPU box that runs a real Minecraft
client + OBS to film the stream) is a **different decision**, owned by E1-R6.
Do not pay for a 24/7 cloud GPU just to host this little server — that would
cost **10–50×** more for no benefit.

## Recommendation

**Run the 24/7 server on a small cloud Linux VPS.** Concrete spec:

| Spec | Recommended | Why |
|------|-------------|-----|
| **OS** | Ubuntu Server 24.04 LTS (headless, no desktop) | The server is headless (Paper `--nogui`). Linux LTS = long support, matches the E2-1 Debian/Ubuntu path. No display needed. |
| **CPU** | 4 vCPU, modern, good single-core speed | Minecraft's world tick is largely **single-threaded** — single-core speed matters more than core count. 4 vCPU leaves headroom for backups/health checks. |
| **RAM** | **8 GB** | E2-1 boots with a **2 GB** heap default; that's a *minimum learning* size. For a 24/7 world with `max-players=20` and `view-distance=10`, run a **4 GB JVM heap** (matches the `-Xms4G -Xmx4G` example in E1-R1 / decision 0001), leaving ~4 GB for the OS, backups, and later co-resident processes. Set it with `MEM=4G scripts/minecraft/start-server.sh`. |
| **Disk** | 80 GB SSD | Paper jar + a normal world is a few GB and grows slowly; the rest is headroom for world growth and **on-host backups** (E2-5). **No recording buffer here** — recording lives on the capture host (E1-R6), not this server. |
| **GPU** | **None** | The Paper server renders nothing. A GPU is only needed on the *capture* host (E1-R6 / decision 0006), which is a separate machine. |

**Estimated cost: ~$15–25 / month** for that spec from a budget-VPS provider
(e.g. a Hetzner CPX31-class instance ≈ €15/mo; mainstream providers'
equivalent 8 GB tiers run ~$40–50/mo — pick on price/region). Figures are
rough and **as of 2026-05**; treat them as order-of-magnitude, not quotes.

**If you already own an always-on machine** (a spare desktop, a mini PC, a
Mac mini that can stay on), use it instead — it's the cheapest option and the
E2-1 runbook already runs there. Accept that **home power/internet outages =
stream down**, with no provider SLA. This is exactly the "owner's machine"
path decision 0006 calls out for early spikes.

## Options compared

Rough monthly cost is for an always-on host at the spec above; "resilience"
is how well it survives unattended for weeks.

| Option | Rough $/mo | 24/7 resilience | Pros | Cons |
|--------|-----------|-----------------|------|------|
| **Local always-on machine** (spare PC / mini PC / Mac mini you own) | ~$0–15 (electricity only) | **Low–medium** — no SLA; dies with home power/ISP; you are the ops team | Cheapest; zero new accounts; can co-locate with a local capture box (see below); full hardware control | No redundancy; home outages take the show down; noise/heat; you patch & monitor it |
| **Cloud VPS** (headless Linux, 4 vCPU / 8 GB / 80 GB) — **recommended** | **~$15–50** | **High** — provider power/network redundancy, easy reboot/console, snapshots | Reliable & cheap; reproducible OS; provider handles power/network; trivial to resize | Recurring bill; you still patch the OS; not GPU-capable (fine — server needs none) |
| **Cloud GPU instance** (display + GPU, for real-client capture) | **~$350–1,100+** | High | Can also run the E1-R6 capture stack (real client + OBS) | **Wildly overpriced for a headless server**; only justified if it's *also* the capture host running 24/7 — see below |

Takeaway: the headless server belongs on the **cheap** tier (local always-on
box or a small VPS). A cloud GPU instance is only ever in scope as the
*capture* host, never as a place to park this server for its own sake.

## Co-location with the capture host (E1-R6)

Decision **0006** (`docs/decisions/0006-video-capture.md`, E1-R6, issue #523)
says production capture uses a **real Minecraft Java client + OBS**, which
needs a **display-capable, GPU-capable host** and disk for local recording
buffers. That is a much heavier (and pricier) machine than this server needs.

**Should the Minecraft server co-locate on that capture host?**

- **On a *local* always-on workstation that already has a GPU + display:**
  **Yes — co-locate.** One box runs both the server and the capture stack at
  near-zero marginal cost (you already own it). This is the cheapest whole
  system and matches the decision 0006 "owner's machine for the first stream
  spike" path. Tradeoff: a single point of failure, and capture load (OBS,
  client) competes with the server for CPU — give the server its 4 GB heap
  and watch tick health (E2-6).
- **In the cloud:** **No — keep them separate.** A 24/7 cloud GPU instance is
  **~$350–1,100+/mo**; a headless VPS for the server is **~$15–50/mo**.
  Co-locating in the cloud means paying GPU prices to host a program that
  needs no GPU. Run the durable server on the cheap VPS and treat the
  GPU/display capture host as a **separate, on-demand** machine owned by
  E1-R6 / E13 — spun up when actually streaming, not left running to babysit
  a 2–4 GB Java process.

**Recommended posture:** durable Minecraft server on the cheap tier (local
always-on box *or* small VPS); GPU/display capture host is a distinct concern
sized and scheduled by E1-R6 / E13. Co-locate **only** when that capture host
is a local machine you already keep running anyway.

## What this does NOT cover (on purpose)

- **Provisioning automation / Infrastructure-as-Code (IaC).** No Terraform,
  Ansible, cloud-init, or one-command provisioning here. This issue **decides
  and documents** the host; turning the recommendation into automated
  provisioning is explicitly **out of scope** and deferred to later ops work.
  The E2-1 start script still works by hand on whichever host you pick.
- **Auto-restart / crash recovery** — that's
  [E2-4](https://github.com/bradtaylorsf/livestreamtoagi/issues/529), now
  documented in [supervision.md](./supervision.md) (the systemd unit you
  install on the host chosen here).
- **Backups & restore** (which is part of the disk budget above) — that's
  [E2-5](https://github.com/bradtaylorsf/livestreamtoagi/issues/530).
- **Health checks / status endpoint** — that's
  [E2-6](https://github.com/bradtaylorsf/livestreamtoagi/issues/531).
- **Sizing/scheduling the GPU capture host itself** — owned by E1-R6
  (`docs/decisions/0006-video-capture.md`) and E13.

## Cross-references

- **E1-R6 — Video capture host:** `docs/decisions/0006-video-capture.md`
  (issue [#523](https://github.com/bradtaylorsf/livestreamtoagi/issues/523)) —
  defines the GPU/display capture host this server deliberately does **not**
  try to be; see [§ Co-location](#co-location-with-the-capture-host-e1-r6).
- **E1-R1 — Version & sizing basis:**
  `docs/decisions/0001-minecraft-version-and-server.md` (Paper 1.21.6 /
  Java 21, the `-Xms4G -Xmx4G` example the RAM recommendation is built on).
- **E2-1 — Run the server:** [server-setup.md](./server-setup.md)
  (issue [#526](https://github.com/bradtaylorsf/livestreamtoagi/issues/526)) —
  the runbook and `scripts/minecraft/start-server.sh` you run *on* the host
  chosen here; `MEM=4G` is the override that applies the recommended heap.
- **E2-2 — World as input:** [world-config.md](./world-config.md).
- **Plan:** `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` → §5, **E2-3**.
