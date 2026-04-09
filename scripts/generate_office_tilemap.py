#!/usr/bin/env python3
"""
Generate a multi-room office tilemap with different floor types per room.
Combines 5 Wang tilesets into one spritesheet and produces tilemap JSON.
"""

import json
from pathlib import Path
from PIL import Image

TILE_SIZE = 32
MAP_W = 40
MAP_H = 22

# Tileset files (each 128x128 = 4x4 grid of 16 Wang tiles)
TILESET_DIR = Path(__file__).parent.parent / "frontend" / "assets" / "tilesets" / "office"

TILESETS = [
    ("tileset.png", "tileset_metadata.json"),           # 0: original blue-grey carpet
    ("tileset_hardwood.png", "tileset_hardwood_metadata.json"),  # 1: warm beige carpet (Vera)
    ("tileset_whitetile.png", "tileset_whitetile_metadata.json"), # 2: white kitchen tile
    ("tileset_teal.png", "tileset_teal_metadata.json"),  # 3: teal carpet (Aurora)
    ("tileset_purple.png", "tileset_purple_metadata.json"), # 4: purple carpet (Grok)
    ("tileset_bluegrey.png", "tileset_bluegrey_metadata.json"), # 5: dark blue-grey carpet
    ("tileset_concrete.png", "tileset_concrete_metadata.json"),  # 6: grey concrete (Rex)
    ("tileset_olive.png", "tileset_olive_metadata.json"),  # 7: olive green carpet (Alpha)
]

# Wang tile corner patterns → position index in spritesheet (0-15)
# Pattern key: (NW, NE, SW, SE) where 0=lower(wall), 1=upper(floor)
WANG_PATTERN_TO_INDEX = {}

def build_wang_lookup(metadata_path: Path) -> dict:
    """Build corner pattern → spritesheet index mapping from metadata."""
    with open(metadata_path) as f:
        meta = json.load(f)

    lookup = {}
    corner_map = {"lower": 0, "upper": 1}
    for tile in meta["tileset_data"]["tiles"]:
        c = tile["corners"]
        pattern = (corner_map[c["NW"]], corner_map[c["NE"]], corner_map[c["SW"]], corner_map[c["SE"]])
        # Spritesheet position from bounding box
        bb = tile["bounding_box"]
        idx = (bb["y"] // TILE_SIZE) * 4 + (bb["x"] // TILE_SIZE)
        lookup[pattern] = idx
    return lookup

# All tilesets share the same Wang layout, so any metadata works
WANG_LOOKUP = None  # Will be initialized in main()

# Room definitions: (name, tileset_index, x1, y1, x2, y2) — tile coords, inclusive
# Bounds EXPANDED to cover wall gaps so no tile falls back to default blue-grey.
# Each room extends to the wall line (shared with neighbor). Last room listed wins overlap.
# Layout (40x22):
#   Top half (rows 0-10):
#     Vera's Office (beige) | Kitchen (white tile) | Dev Bay: Sentinel+Fork+Pixel (blue-grey)
#   Horizontal wall at row 10
#   Bottom half (rows 10-21):
#     Rex's Workshop (concrete) | Aurora's Studio (teal) | Grok's Space (purple) | Meeting (blue-grey)
#     (bottom-right corner) Alpha+Management (olive green)
ROOMS = [
    # Top row — rows 0-10 (tile row 10 is the wall-face row, uses top room's tileset)
    ("workspace_vera",       1, 0, 0, 9, 10),      # warm beige
    ("kitchen",              2, 10, 0, 20, 10),     # white tile
    # Dev Bay — open-plan with 3 agent desks
    ("workspace_sentinel",   0, 21, 0, 39, 10),     # original blue-grey
    ("workspace_fork",       0, 21, 0, 39, 10),     # same area
    ("workspace_pixel",      0, 21, 0, 39, 10),     # same area
    # Bottom row — rows 11-21 (row 11 has wall-face transition from bottom room tilesets)
    ("workspace_rex",        6, 0, 11, 9, 21),      # grey concrete
    ("workspace_aurora",     3, 10, 11, 20, 21),    # teal
    ("workspace_grok",       4, 21, 11, 30, 21),    # purple
    ("meeting_area",         0, 31, 11, 39, 16),    # original blue-grey
    ("workspace_alpha",      7, 31, 17, 39, 21),    # olive green
    ("workspace_management", 7, 31, 17, 39, 21),    # shares Alpha space
]

# No interior wall vertices — rooms are directly adjacent.
# Color difference between rooms IS the visual boundary.
# Interior doors are not needed (no walls to cut through).
VDOORS = []
HDOORS = []

# Exterior doors — openings in the outer wall for entrances/exits
EXTERIOR_DOORS = [
    # Left entrance (Rex's wall)
    (0, 15), (0, 16),
    # Right entrance (Meeting area wall)
    (39, 13), (39, 14),
]


def get_room_tileset(col: int, row: int) -> int:
    """Get the tileset index for a given tile position based on which room it's in."""
    # Deduplicated rooms (some agents share a room)
    seen = set()
    for name, ts_idx, x1, y1, x2, y2 in ROOMS:
        key = (ts_idx, x1, y1, x2, y2)
        if key in seen:
            continue
        seen.add(key)
        if x1 <= col <= x2 and y1 <= row <= y2:
            return ts_idx
    return 0  # default blue-grey for corridors/unassigned


def build_vertex_grid():
    """
    Build a (MAP_W+1) x (MAP_H+1) vertex grid.
    0 = wall vertex, 1 = floor vertex.
    Vertices are at tile corners: vertex (vx, vy) is the top-left corner of tile (vx, vy).
    """
    # Start with all walls
    vgrid = [[0] * (MAP_W + 1) for _ in range(MAP_H + 1)]

    # Mark room interiors as floor (all 4 corners of each room tile)
    for name, ts_idx, x1, y1, x2, y2 in ROOMS:
        for vy in range(y1, y2 + 2):  # +2 because we need the bottom-right vertex too
            for vx in range(x1, x2 + 2):
                if 0 <= vx <= MAP_W and 0 <= vy <= MAP_H:
                    vgrid[vy][vx] = 1

    # Outer walls only — thin interior walls drawn programmatically via Phaser Graphics
    for vx in range(MAP_W + 1):
        vgrid[0][vx] = 0
        vgrid[MAP_H][vx] = 0
    for vy in range(MAP_H + 1):
        vgrid[vy][0] = 0
        vgrid[vy][MAP_W] = 0

    # Re-open door positions (set vertices back to floor)
    all_doors = VDOORS + HDOORS + EXTERIOR_DOORS
    for dx, dy in all_doors:
        # For a door at tile (dx, dy), open the vertices around it
        # This makes the tile at (dx, dy) have floor corners
        for vy in range(dy, dy + 2):
            for vx in range(dx, dx + 2):
                if 0 <= vx <= MAP_W and 0 <= vy <= MAP_H:
                    vgrid[vy][vx] = 1

    return vgrid


def build_ground_layer(vgrid):
    """Build ground tile layer using Wang tile lookup per room tileset."""
    data = []
    for row in range(MAP_H):
        for col in range(MAP_W):
            # Get 4 corner values for this tile
            nw = vgrid[row][col]
            ne = vgrid[row][col + 1]
            sw = vgrid[row + 1][col]
            se = vgrid[row + 1][col + 1]
            pattern = (nw, ne, sw, se)

            # Get spritesheet tile index (0-15) from Wang lookup
            tile_idx = WANG_LOOKUP.get(pattern, 6)  # fallback to pure wall

            # Determine which tileset to use based on room
            # Room bounds are expanded to cover walls, so every tile belongs to a room.
            # Each room's tileset has matching wall colors, eliminating blue-grey bleed.
            ts_idx = get_room_tileset(col, row)

            # Tile ID = tileset_offset + tile_index + 1 (Tiled uses 1-based)
            firstgid = ts_idx * 16 + 1
            tile_id = firstgid + tile_idx
            data.append(tile_id)
    return data


def build_collision_layer(vgrid):
    """Build collision layer: 1 = wall (non-walkable), 0 = walkable."""
    data = []
    for row in range(MAP_H):
        for col in range(MAP_W):
            nw = vgrid[row][col]
            ne = vgrid[row][col + 1]
            sw = vgrid[row + 1][col]
            se = vgrid[row + 1][col + 1]
            # Tile is walkable only if ALL corners are floor
            if nw == 1 and ne == 1 and sw == 1 and se == 1:
                data.append(0)
            else:
                data.append(1)
    return data


def build_areas():
    """Build named area definitions for the tilemap."""
    areas = {}

    # Manual sub-zone overrides for shared rooms
    # Dev Bay (cols 22-38, rows 1-9) split into 3 desk zones
    DEV_BAY_OVERRIDES = {
        "workspace_sentinel": (23, 2, 5, 7),  # left section (5x7 tiles)
        "workspace_fork":     (29, 2, 5, 7),  # middle section
        "workspace_pixel":    (34, 2, 4, 7),  # right section
    }
    # Alpha and Management share bottom-right
    ALPHA_MGMT_OVERRIDES = {
        "workspace_alpha":      (33, 18, 5, 2),  # bottom part
        "workspace_management": (33, 18, 5, 2),  # same spot (elevated platform)
    }

    overrides = {**DEV_BAY_OVERRIDES, **ALPHA_MGMT_OVERRIDES}

    for name, ts_idx, x1, y1, x2, y2 in ROOMS:
        if name in areas:
            continue  # skip duplicates
        if name in overrides:
            ox, oy, ow, oh = overrides[name]
            areas[name] = {
                "x": ox * TILE_SIZE,
                "y": oy * TILE_SIZE,
                "width": ow * TILE_SIZE,
                "height": oh * TILE_SIZE,
            }
        else:
            # Inset by 1 tile from walls for usable area
            px = (x1 + 1) * TILE_SIZE
            py = (y1 + 1) * TILE_SIZE
            pw = (x2 - x1 - 1) * TILE_SIZE
            ph = (y2 - y1 - 1) * TILE_SIZE
            if pw > 0 and ph > 0:
                areas[name] = {"x": px, "y": py, "width": pw, "height": ph}

    # Add shared areas not tied to a room definition
    areas["workshop"] = {"x": 23 * TILE_SIZE, "y": 5 * TILE_SIZE, "width": 15 * TILE_SIZE, "height": 4 * TILE_SIZE}

    return areas


def combine_tilesets():
    """Combine all tileset PNGs into one horizontal spritesheet."""
    images = []
    for ts_file, meta_file in TILESETS:
        path = TILESET_DIR / ts_file
        if path.exists():
            img = Image.open(path)
            if img.size == (128, 128):
                images.append(img)
            else:
                print(f"Warning: {ts_file} is {img.size}, expected (128, 128). Skipping.")
                # Create placeholder
                images.append(Image.new("RGBA", (128, 128), (60, 60, 74, 255)))
        else:
            print(f"Warning: {ts_file} not found. Using placeholder.")
            images.append(Image.new("RGBA", (128, 128), (60, 60, 74, 255)))

    # Combine horizontally: N * 128 wide, 128 tall
    combined = Image.new("RGBA", (128 * len(images), 128))
    for i, img in enumerate(images):
        combined.paste(img, (i * 128, 0))

    output_path = TILESET_DIR / "office_tiles_combined.png"
    combined.save(output_path)
    print(f"Combined tileset saved: {output_path} ({combined.size[0]}x{combined.size[1]})")
    return output_path


def generate_tilemap():
    """Generate the complete tilemap JSON."""
    vgrid = build_vertex_grid()
    ground = build_ground_layer(vgrid)
    collision = build_collision_layer(vgrid)
    areas = build_areas()

    # Build tileset entries — each references its own 128x128 image
    tilesets = []
    tileset_entries = [
        ("office_tiles",           "tileset"),
        ("office_tiles_hardwood",  "tileset_hardwood"),
        ("office_tiles_whitetile", "tileset_whitetile"),
        ("office_tiles_teal",      "tileset_teal"),
        ("office_tiles_purple",    "tileset_purple"),
        ("office_tiles_bluegrey",  "tileset_bluegrey"),
        ("office_tiles_concrete",  "tileset_concrete"),
        ("office_tiles_olive",     "tileset_olive"),
    ]
    for i, (name, image_key) in enumerate(tileset_entries):
        tilesets.append({
            "columns": 4,
            "firstgid": i * 16 + 1,
            "image": image_key,
            "imageheight": 128,
            "imagewidth": 128,
            "margin": 0,
            "name": name,
            "spacing": 0,
            "tilecount": 16,
            "tileheight": TILE_SIZE,
            "tilewidth": TILE_SIZE,
        })

    tilemap = {
        "compressionlevel": -1,
        "height": MAP_H,
        "infinite": False,
        "layers": [
            {
                "data": ground,
                "height": MAP_H,
                "id": 1,
                "name": "Ground",
                "opacity": 1,
                "type": "tilelayer",
                "visible": True,
                "width": MAP_W,
                "x": 0,
                "y": 0,
            },
            {
                "data": collision,
                "height": MAP_H,
                "id": 2,
                "name": "Collision",
                "opacity": 1,
                "type": "tilelayer",
                "visible": True,
                "width": MAP_W,
                "x": 0,
                "y": 0,
            },
        ],
        "nextlayerid": 3,
        "nextobjectid": 1,
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "tiledversion": "1.10.2",
        "tileheight": TILE_SIZE,
        "tilesets": tilesets,
        "tilewidth": TILE_SIZE,
        "type": "map",
        "version": "1.10",
        "width": MAP_W,
        "properties": [
            {
                "name": "areas",
                "type": "string",
                "value": json.dumps(areas),
            }
        ],
    }

    output_path = TILESET_DIR / "tilemap_office.json"
    with open(output_path, "w") as f:
        json.dump(tilemap, f, indent=2)
    print(f"Tilemap saved: {output_path}")
    print(f"  {MAP_W}x{MAP_H} tiles, {len(areas)} areas")
    for name, rect in areas.items():
        print(f"    {name}: ({rect['x']}, {rect['y']}) {rect['width']}x{rect['height']}px")


def main():
    global WANG_LOOKUP

    # Build Wang lookup from any metadata (all share same layout)
    meta_path = TILESET_DIR / "tileset_metadata.json"
    WANG_LOOKUP = build_wang_lookup(meta_path)
    print(f"Wang lookup: {len(WANG_LOOKUP)} patterns")

    # Combine tilesets
    combine_tilesets()

    # Generate tilemap
    generate_tilemap()

    print("\nDone! Next steps:")
    print("1. Update MainScene.ts to load 'office_tiles_combined' spritesheet")
    print("2. Update workspace definitions to match new area names")
    print("3. Update SHARED_FURNITURE positions for new room layout")


if __name__ == "__main__":
    main()
