#!/usr/bin/env python3
"""
sor-parse.py — Read sor.yaml and emit values for bash scripts.

Usage:
    sor-parse.py project_name
    sor-parse.py layer_count
    sor-parse.py layer <N> <field>        # 0-indexed layer
    sor-parse.py layer <N> surface        # newline-separated surface files
    sor-parse.py layer <N> contracts      # oracle contract test pattern
    sor-parse.py layer <N> scored         # "true" or "false"
    sor-parse.py layer <N> scored_tests   # scored test pattern
    sor-parse.py layer <N> metrics        # "name:extract:weight" per line
    sor-parse.py layer <N> threshold <key>
    sor-parse.py default <key>
    sor-parse.py always_frozen            # newline-separated frozen paths
    sor-parse.py frozen_for <N>           # all frozen paths when working on layer N
    sor-parse.py layer_name_to_index <name>

Looks for sor.yaml in: $SOR_CONFIG, ./sor.yaml, or project root.
"""

import os
import sys
import yaml

def find_config():
    candidates = [
        os.environ.get("SOR_CONFIG", ""),
        os.path.join(os.getcwd(), "sor.yaml"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    print("ERROR: sor.yaml not found", file=sys.stderr)
    sys.exit(1)

def load():
    with open(find_config()) as f:
        return yaml.safe_load(f)

def main():
    cfg = load()
    args = sys.argv[1:]
    if not args:
        print("Usage: sor-parse.py <command> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = args[0]

    if cmd == "project_name":
        print(cfg.get("project_name", "Unnamed Project"))

    elif cmd == "layer_count":
        print(len(cfg.get("layers", [])))

    elif cmd == "layer":
        idx = int(args[1])
        layers = cfg.get("layers", [])
        if idx >= len(layers):
            print(f"ERROR: layer {idx} out of range (have {len(layers)})", file=sys.stderr)
            sys.exit(1)
        layer = layers[idx]
        field = args[2]

        if field == "name":
            print(layer["name"])
        elif field == "surface":
            for s in layer.get("surface", []):
                print(s)
        elif field == "contracts":
            print(layer.get("oracle", {}).get("contracts", ""))
        elif field == "scored":
            print("true" if layer.get("oracle", {}).get("scored", False) else "false")
        elif field == "scored_tests":
            print(layer.get("oracle", {}).get("scored_tests", ""))
        elif field == "metrics":
            for m in layer.get("oracle", {}).get("metrics", []):
                print(f"{m['name']}:{m['extract']}:{m['weight']}")
        elif field == "threshold":
            key = args[3]
            val = layer.get("thresholds", {}).get(key)
            if val is None:
                val = cfg.get("defaults", {}).get(key, "")
            print(val)
        else:
            print(f"ERROR: unknown field '{field}'", file=sys.stderr)
            sys.exit(1)

    elif cmd == "default":
        key = args[1]
        print(cfg.get("defaults", {}).get(key, ""))

    elif cmd == "always_frozen":
        for p in cfg.get("always_frozen", []):
            print(p)

    elif cmd == "frozen_for":
        # Returns all frozen paths when working on layer N:
        #   always_frozen + surface files from all layers < N
        n = int(args[1])
        for p in cfg.get("always_frozen", []):
            print(p)
        layers = cfg.get("layers", [])
        for i in range(n):
            for s in layers[i].get("surface", []):
                print(s)

    elif cmd == "layer_name_to_index":
        name = args[1].lower()
        for i, layer in enumerate(cfg.get("layers", [])):
            if layer["name"].lower() == name:
                print(i)
                sys.exit(0)
        print(f"ERROR: no layer named '{name}'", file=sys.stderr)
        sys.exit(1)

    else:
        print(f"ERROR: unknown command '{cmd}'", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
