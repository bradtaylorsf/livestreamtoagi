# Decision 0001: Minecraft Version And Server Software

Status: accepted for coding

Research date: 2026-05-18

Related issue: #518, E1-R1

## Non-Technical Summary

We will start the Minecraft pivot on a private Minecraft Java Edition server using
Paper 1.21.6. Paper is the server program. Minecraft Java Edition is the PC
edition that Mineflayer and Mindcraft control. Version 1.21.6 is not the newest
Minecraft protocol, but it is the version Mindcraft explicitly recommends and
already patches around. That makes it the right first version for a beginner-safe
24/7 build.

## Decision

- Minecraft edition: Java Edition.
- Minecraft protocol version for E2 through E8: `1.21.6`.
- Server software: Paper.
- Paper server artifact: `paper-1.21.6-48.jar`.
- Paper artifact SHA-256:
  `35e2dfa66b3491b9d2f0bb033679fa5aca1e1fdf097e7a06a80ce8afeda5c214`.
- Mindcraft upstream to fork and pin:
  `mindcraft-bots/mindcraft@35be480b4cc0bca990278e6103a1426392559d96`.
- Mindcraft upstream branch: `develop`.
- Mindcraft commit date: `2026-05-03 16:11:10 -0700`.
- Mindcraft runtime Node version: Node 20 LTS.
- Paper runtime Java version: Java 21.
- Mindcraft setting: `minecraft_version: "1.21.6"`, not `auto`, after the
  server is provisioned.

## Why This Version

Mindcraft's current README says it supports Minecraft Java Edition up to
`1.21.11`, but recommends `1.21.6`. Its default `settings.js` also uses
`1.21.6` as the example fixed version. The fork contains a patch specifically
against `minecraft-data` for `1.21.6`, which is a strong sign that the authors
are actively smoothing rough edges on that version.

Mineflayer itself supports `1.21.11`, so newer Minecraft is possible later, but
the first coding pass should optimize for fewer moving parts. The current Paper
download API already has stable builds for both `1.21.6` and `1.21.11`; choosing
`1.21.6` is a compatibility choice, not a lack-of-availability choice.

## Why Paper

Paper is a headless server distribution with production-oriented docs, stable
build downloads, and a simple `--nogui` command. It is a better 24/7 operations
target than a GUI-launched LAN world. We do not need Fabric for phase 1 because
we are not starting with gameplay-changing mods. Vanilla is simpler in theory,
but Paper gives us better operational hooks and is already directly addressed in
Mindcraft's source comments.

## Rejected Alternatives

- Vanilla server jar: acceptable fallback, but less useful for 24/7 operations
  and plugin/admin tooling.
- Fabric: defer until a specific mod is required. It adds mod compatibility
  decisions before we have a vertical slice.
- Minecraft `1.21.11`: supported by Mineflayer, but not Mindcraft's recommended
  starting point. Also, the browser-render capture stack has unresolved visual
  compatibility issues for versions after `1.21.4`.
- Paper latest `26.1.2`: not compatible with the current Mindcraft support
  envelope. Do not chase latest for this pivot.

## Technical Implications

- E2 server scripts should download Paper by version/build, verify SHA-256, and
  run with Java 21:

```bash
java -Xms4G -Xmx4G -jar paper-1.21.6-48.jar --nogui
```

- E2 should avoid `port=-1` auto-detection in production scripts. Use a fixed
  port, initially `55916` to match Mindcraft defaults and examples.
- E3 should fork Mindcraft from the pinned commit before local patches.
- E3 should use Node 20. Mindcraft says Node v18 or v20 LTS are recommended and
  warns that Node v24+ may break native dependencies.
- E13 should not depend on Prismarine Viewer compatibility with `1.21.6` for
  the production stream. See decision 0006.

## Beginner Glossary

- Java Edition: the desktop/server edition of Minecraft that Mineflayer can
  control. Bedrock Edition is a different network/protocol ecosystem.
- Server jar: a Java program that runs the world. Players and bots connect to it.
- Paper: a popular optimized Minecraft Java server. It can run without a GUI.
- Vanilla: Mojang's official server, without Paper's extra admin/performance
  features.
- Fabric: a mod loader. Useful when we need mods, unnecessary for the first
  slice.
- Headless: runs in a terminal with no game window.
- World seed: a number/string that controls how a new world is generated.
- Protocol version: the exact Minecraft network version clients and bots must
  speak.

## Evidence

- Mindcraft README requirements and Node note:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/README.md#L23-L24
- Mindcraft default settings:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/settings.js#L1-L5
- Mindcraft `1.21.6` patch:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/patches/minecraft-data%2B3.97.0.patch#L1-L11
- Mindcraft version check:
  https://github.com/mindcraft-bots/mindcraft/blob/35be480b4cc0bca990278e6103a1426392559d96/src/mindcraft/mcserver.js#L138-L153
- Mineflayer supported versions:
  https://github.com/PrismarineJS/mineflayer#features
- Paper Java requirements and `--nogui` command:
  https://docs.papermc.io/paper/getting-started/#requirements
- Paper downloads service:
  https://docs.papermc.io/misc/downloads-service/
