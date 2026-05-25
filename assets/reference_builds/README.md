# Reference Builds Library (E22-6)

Curated reference blueprint images that the
`BlueprintDecomposer` (`core/minecraft/build_plan_decomposer.py`) turns
into structured `BuildPlan`s for the deterministic Minecraft macro
compiler (E22-7).

Each subdirectory holds:

- `image.png` — the reference image (top-down or isometric blueprint).
- `source_credit.md` — provenance and license for the image.
- `intent_hints.yaml` — human-curated hints fed to the vision model
  (viewpoint, tile-to-block scale, structural notes, features to ignore).

Adding a new structure type means:

1. Adding an entry to `StructureType` in
   `core/agents/build_intent.py`.
2. Creating a new folder here with the three files above.
3. Re-running the cached decomposer to materialize a new
   `BuildPlan` for the new structure.
