# Director V2 Plan-Build Evidence

Use this reference when verifying whether a Director V2 Minecraft plan-build run actually built the requested structure.

## Metrics Snippet

```bash
python - <<'PY'
import json
from pathlib import Path

run = Path("logs/soak/<timestamp>")
counts = {
    "planAndBuild_action_started": 0,
    "generation_completed": 0,
    "execution_completed": 0,
    "execution_success": 0,
}
success = []

for line in (run / "timeline.ndjson").read_text().splitlines():
    evt = json.loads(line)
    payload = evt.get("payload") or {}
    event_type = evt.get("event_type")
    if event_type == "action.started" and payload.get("action") == "action:planAndBuild":
        counts["planAndBuild_action_started"] += 1
    elif event_type == "build_plan.generation.completed":
        counts["generation_completed"] += 1
    elif event_type == "build_plan.execution.completed":
        counts["execution_completed"] += 1
        if " success:" in str(payload.get("result", "")):
            counts["execution_success"] += 1
            success.append(payload)

print(json.dumps(counts, indent=2))
for payload in success:
    print(json.dumps({
        "plan_id": payload.get("plan_id"),
        "owner": payload.get("owner"),
        "origin": payload.get("origin"),
        "verified_blocks": payload.get("verified_blocks"),
        "metric": payload.get("metric"),
        "result": payload.get("result"),
    }, indent=2))
PY
```

## Live World Block Sample

Use this when a gameplay screenshot is unavailable. Adjust `origin`, bounds, and output path from the plan event.

```bash
node --input-type=module - <<'NODE'
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';
import path from 'node:path';

const cwd = process.cwd();
const require = createRequire(path.join(cwd, 'mindcraft/package.json'));
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const out = path.join(cwd, 'logs/soak/<timestamp>/minecraft-build-blocks.json');
const origin = { x: 4, y: 64, z: -4 };
const ignored = new Set(['air', 'grass_block', 'dirt', 'short_grass', 'tall_grass']);

const bot = mineflayer.createBot({
  host: '127.0.0.1',
  port: 25566,
  username: 'WorldInspector',
  auth: 'offline',
  version: '1.21.6',
});

let done = false;
function finish(code = 0) {
  if (done) return;
  done = true;
  try { bot.quit(); } catch {}
  setTimeout(() => process.exit(code), 250);
}

bot.once('spawn', async () => {
  await new Promise((resolve) => setTimeout(resolve, 2500));
  const blocks = [];
  for (let y = origin.y - 1; y <= origin.y + 6; y += 1) {
    for (let x = origin.x - 7; x <= origin.x + 7; x += 1) {
      for (let z = origin.z - 7; z <= origin.z + 7; z += 1) {
        const block = bot.blockAt(new Vec3(x, y, z));
        if (block && !ignored.has(block.name)) {
          blocks.push({ x, y, z, name: block.name });
        }
      }
    }
  }
  writeFileSync(out, JSON.stringify({ origin, blocks }, null, 2));
  console.log(`wrote ${blocks.length} blocks to ${out}`);
  finish(0);
});

bot.on('error', (error) => {
  console.error(error?.stack || error);
  finish(1);
});

setTimeout(() => {
  console.error('timeout inspecting Minecraft world');
  finish(1);
}, 20000);
NODE
```

## Verdict Rubric

- **Real structure**: compact footprint, requested material palette, vertical continuity, and recognizable elements such as floor/foundation, walls/corners, entry, roof/roofline, lighting/interior detail.
- **Partial structure**: some coherent footprint or wall/foundation evidence, but missing key requested elements or low completion.
- **Scattered blocks**: isolated markers, unconnected placements, multiple agents placing unrelated blocks, or blocks that do not match the requested plan.

For cabin requests, prefer at least 24 verified blocks; 32+ verified blocks with base, walls, roofline, door gap, and torch/detail is enough for a compact cabin smoke.
