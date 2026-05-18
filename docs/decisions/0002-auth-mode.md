# Decision 0002: Auth Mode

Status: accepted for local coding; production launch has a human/legal gate

Research date: 2026-05-18

Related issue: #519, E1-R2

## Non-Technical Summary

For the first Minecraft coding phase, the server will be private and isolated.
Bots will connect in Minecraft "offline mode", which means the server does not
ask Microsoft to verify each bot account. This keeps the Alpha slice and local
development simple.

Offline mode is not safe on the open internet. Anyone who can reach the server
can pretend to be any bot username. So the server must be reachable only from the
same machine or a private network.

Before a monetized public 24/7 launch, we need a human decision: either buy/use
Microsoft-authenticated Minecraft Java accounts for the bots and switch to
online mode, or get explicit legal comfort that the private offline-bot topology
is acceptable for the project.

## Decision

Use two auth postures:

1. Local development, E2 through E8 vertical slice:
   - Paper `online-mode=false`.
   - Mindcraft `auth: "offline"`.
   - Fixed bot usernames matching generated Mindcraft profiles.
   - Server bound to localhost or private network only.

2. Public/monetized production launch:
   - Blocked until a human/legal decision.
   - Preferred conservative launch path: `online-mode=true` with legitimate
     Minecraft Java accounts for camera and bot identities.
   - Acceptable only with sign-off: keep `online-mode=false` on a private,
     non-public server where only internal bots connect.

## Required Security Rules For Offline Mode

- Do not expose the Minecraft server port publicly.
- On a cloud host, allow the server port only from localhost, the bot host, or a
  private VPN such as Tailscale/WireGuard.
- Use a whitelist anyway, but do not treat it as real identity security in
  offline mode.
- Do not allow public players in the phase-1 offline server.
- Keep the camera client and bot processes on the same host or private network.
- If any human needs admin access, use VPN access first, then Minecraft access.

## What Offline Mode Means

Minecraft `online-mode=true` means the server verifies joining players through
Microsoft/Mojang authentication. Minecraft `online-mode=false` means the server
accepts the username presented by the client. That is convenient for bots and
dangerous if exposed publicly.

Mindcraft's default settings already use `auth: "offline"` and the README says
online servers require official Microsoft/Minecraft accounts.

## Files That Should Follow This Decision

- E2 server runbook: document `online-mode=false` as a private-dev setting only.
- E2 server config: set firewall/private-network requirements next to the
  setting.
- E3 Mindcraft settings: `auth: "offline"` for local profile generation.
- E11 kill switch: must stop both bots and server even in offline mode.
- E13 production launch checklist: cannot mark production-ready until the
  auth/legal gate is resolved.

## Evidence

- Mindcraft default auth setting:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/settings.js#L1-L5
- Mindcraft online-server instructions:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/README.md#L90-L102
- ViaProxy offline/online auth notes:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/services/viaproxy/README.md#L20-L40
- Minecraft server/hosting commercial guidelines:
  https://www.minecraft.net/en-us/usage-guidelines#commercial-use
