# Minecraft Server: BlueMap setup for screenshot capture

The `RefinementLoop` (E22) compares the source blueprint image against a
screenshot of the built structure. We get that screenshot by driving a
headless Chromium against the **BlueMap** Paper plugin's live web map.

## Install the BlueMap Paper plugin

1. Download the latest BlueMap Paper/Spigot plugin JAR from
   <https://bluemap.bluecolored.de/> (project page on Modrinth / GitHub
   releases — pick the build matching your server's MC version).
2. Drop the JAR into your Paper server's `plugins/` directory:
   `minecraft-server/plugins/BlueMap-<version>-paper.jar`.
3. Restart the server. On first startup BlueMap creates
   `plugins/BlueMap/` with a config; defaults work out of the box.
4. Run `/bluemap render` (in-game or via RCON) once to generate the
   initial tiles. Subsequent edits update incrementally.

## Default port

BlueMap exposes an HTTP web map on **`:8100`** by default. If you bind a
different port edit `plugins/BlueMap/webserver.conf` and set
`BLUEMAP_URL` accordingly in your `.env`:

```bash
BLUEMAP_URL=http://localhost:8100
BLUEMAP_WORLD=world            # match your world folder name
BLUEMAP_ZOOM=4                 # higher = further zoom out
BLUEMAP_TIMEOUT_SECONDS=15
```

## How the screenshot pipeline uses it

When `RCON_HOST`, `RCON_PASSWORD`, and `BLUEMAP_URL` are all set,
`rcon_executor_from_env()` wires a `screenshot_fn` that:

1. Computes the build's centroid from the compiled `BuildScript`'s
   command extents.
2. Loads `${BLUEMAP_URL}/#<world>:flat:<cx>,<cy>,<cz>:<zoom>:0:0:0:0:flat`
   in headless Chromium (Playwright).
3. Waits for the BlueMap canvas to render, then snaps a PNG.

The PNG bytes are returned from `RconBuildExecutor.__call__` and flow
into the refinement loop's `GeminiComparisonProvider`.

## Required Python extras

```bash
uv pip install -e ".[render]"
playwright install chromium
```

The `[render]` extra is shared with the simulation → MP4 pipeline, so
it's already installed wherever video rendering works.
