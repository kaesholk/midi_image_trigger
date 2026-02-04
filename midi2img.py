#!/usr/bin/env python3
"""
Usage:
    python midi_images.py --config config.json [--port "MIDI Port Name"]
"""

import argparse
import json
import os
import sys
import time
import math
from typing import Dict

import mido
import pygame

import corruptize

def load_config(path: str):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("image_folder", "images")
    cfg.setdefault("window", {"width": 800, "height": 600, "bg_color": [0,0,0]})
    cfg.setdefault("scale_mode", "fit")
    cfg.setdefault("notes", {})
    return cfg

def choose_midi_port(port_arg: str = None):
    ports = mido.get_input_names()
    if not ports:
        print("No MIDI input ports found.", file=sys.stderr)
        sys.exit(1)
    if port_arg:
        # try to find exact or substring match
        for p in ports:
            if port_arg == p or port_arg in p:
                return p
        print(f'Port "{port_arg}" not found among available ports. Available ports:', file=sys.stderr)
        for p in ports:
            print("  ", p, file=sys.stderr)
        sys.exit(1)
    # default: first port
    print("Using MIDI input port:", ports[0])
    return ports[0]

def load_images(image_folder: str, note_map: Dict[str, str]):
    loaded = {}
    missing = []
    for note_str, fname in note_map.items():
        path = os.path.join(image_folder, fname)
        if not os.path.isfile(path):
            missing.append((note_str, path))
            continue
        try:
            surf = pygame.image.load(path).convert_alpha()
        except Exception as e:
            print(f"Failed to load image {path}: {e}", file=sys.stderr)
            missing.append((note_str, path))
            continue
        loaded[int(note_str)] = {"surf": surf, "path": path}
    if missing:
        print("Warning: some mapped images were not found or failed to load:", file=sys.stderr)
        for n, p in missing:
            print("  note", n, "->", p, file=sys.stderr)
    return loaded

def scale_surface_to_fit_exact(surf, max_w, max_h):
    """Return a new Surface scaled to fit within (max_w, max_h) preserving aspect ratio."""
    w, h = surf.get_size()
    if w == 0 or h == 0:
        return surf
    # if already smaller, we still may want to scale up to fill cell; keep aspect ratio
    scale = min(max_w / w, max_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    if (new_w, new_h) == (w, h):
        return surf
    return pygame.transform.smoothscale(surf, (new_w, new_h))


def compute_grid_dimensions(n_items, window_w, window_h, padding, min_cell_size):
    """
    Determine number of columns and rows for an n_items grid.
    Strategy: choose cols = ceil(sqrt(n)), rows = ceil(n / cols).
    Return (cols, rows, cell_w, cell_h, left, top)
    """
    if n_items <= 0:
        return 0, 0, 0, 0, 0, 0

    cols = math.ceil(math.sqrt(n_items))
    rows = math.ceil(n_items / cols)

    # try to reduce columns if resulting cell size would be below min_cell_size
    while cols > 1:
        cell_w_candidate = (window_w - (cols + 1) * padding) / cols
        cell_h_candidate = (window_h - (rows + 1) * padding) / rows
        if cell_w_candidate >= min_cell_size and cell_h_candidate >= min_cell_size:
            break
        # increase rows by moving one column to rows (i.e. reduce columns)
        cols -= 1
        rows = math.ceil(n_items / cols)

    cell_w = max(1, int((window_w - (cols + 1) * padding) / cols))
    cell_h = max(1, int((window_h - (rows + 1) * padding) / rows))

    # center grid
    grid_w = cols * cell_w + (cols + 1) * padding
    grid_h = rows * cell_h + (rows + 1) * padding
    left = max(0, int((window_w - grid_w) / 2))
    top = max(0, int((window_h - grid_h) / 2))

    return cols, rows, cell_w, cell_h, left, top

def process_screen(screen: pygame.Surface) -> pygame.Surface:
    # convert screen to numpy array
    arr = pygame.surfarray.array3d(screen)
    processed = corruptize.process_image_array(arr, 0, 1)
    return pygame.surfarray.make_surface(processed)

def main():
    parser = argparse.ArgumentParser(description="Realtime MIDI -> images (display while note held) in a grid")
    parser.add_argument("--config", "-c", default="config.json", help="Path to JSON config")
    parser.add_argument("--port", "-p", default=None, help="MIDI input port name (substring match allowed)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    image_folder = cfg["image_folder"]
    win_w = int(cfg["window"].get("width", 1280))
    win_h = int(cfg["window"].get("height", 720))
    bg_color = tuple(cfg["window"].get("bg_color", [0, 0, 0]))
    notes_map = cfg.get("notes", {})

    grid_cfg = cfg.get("grid", {})
    grid_padding = int(grid_cfg.get("padding", 8))        # space between cells and borders
    cell_margin = int(grid_cfg.get("cell_margin", 8))    # margin inside a cell between image and cell edge
    min_cell_size = int(grid_cfg.get("min_cell_size", 24))

    pygame.init()
    pygame.display.set_caption("MIDI → Images (grid: hold note to display)")
    screen = pygame.display.set_mode((win_w, win_h))
    clock = pygame.time.Clock()

    portname = choose_midi_port(args.port)
    images = load_images(image_folder, notes_map)

    # active notes: note -> {"surf": Surface, "on_time": float}
    active = {}

    try:
        with mido.open_input(portname) as inport:
            print("Listening for MIDI on:", portname)
            running = True
            corruptize.init_worker()
            previous_frame = screen.copy()
            while running:
                # handle pygame events (close window, ESC)
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        running = False
                    elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                        running = False

                # process pending MIDI messages
                for msg in inport.iter_pending():
                    if msg.type == "note_on" and msg.velocity > 0:
                        note = int(msg.note)
                        if note in images:
                            active[note] = {"surf": images[note]["surf"], "on_time": time.time()}
                    elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                        note = int(msg.note)
                        if note in active:
                            del active[note]

                # draw background
                screen.fill(bg_color)

                n_active = len(active)
                if n_active > 0:
                    # Compute grid layout
                    cols, rows, cell_w, cell_h, left, top = compute_grid_dimensions(
                        n_active, win_w, win_h, grid_padding, min_cell_size
                    )

                    # Draw each active image into its grid cell
                    # order deterministically by note number so images don't jump around randomly
                    sorted_notes = sorted(active.keys())
                    for idx, note in enumerate(sorted_notes):
                        row = idx // cols
                        col = idx % cols
                        cell_x = left + grid_padding + col * (cell_w + grid_padding)
                        cell_y = top + grid_padding + row * (cell_h + grid_padding)

                        # compute available area inside cell (leave cell_margin)
                        avail_w = max(1, cell_w - 2 * cell_margin)
                        avail_h = max(1, cell_h - 2 * cell_margin)

                        surf = active[note]["surf"]
                        # scale to fit available area while preserving aspect ratio
                        scaled = scale_surface_to_fit_exact(surf, avail_w, avail_h)

                        sw, sh = scaled.get_size()
                        # center scaled image inside cell
                        pos_x = cell_x + (cell_w - sw) // 2
                        pos_y = cell_y + (cell_h - sh) // 2

                        screen.blit(scaled, (pos_x, pos_y))

                # effects processing
                # takes the screen, runs effects, returns modified screen
                modified = process_screen(screen)
                modified.set_alpha(128)  # half opacity
                screen.blit(modified, (0,0), special_flags=pygame.BLEND_ADD)

                # flip display
                pygame.display.flip()
                clock.tick(30)

    except KeyboardInterrupt:
        print("Interrupted by user, exiting.")
    finally:
        pygame.quit()
        print("Goodbye.")


if __name__ == "__main__":
    main()