#!/usr/bin/env python3
"""Simulate frame drops/duplicates/shuffle for debugging receiver resilience."""

from __future__ import annotations

import argparse
import os
import random
import shutil


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--drop-rate", type=float, default=0.1)
    parser.add_argument("--duplicate-rate", type=float, default=0.0)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    os.makedirs(args.out_dir, exist_ok=True)

    files = [f for f in os.listdir(args.in_dir) if f.lower().endswith(".png")]
    files.sort()

    selected = []
    for name in files:
        if random.random() < args.drop_rate:
            continue
        selected.append(name)
        if args.duplicate_rate > 0 and random.random() < args.duplicate_rate:
            selected.append(name)

    if args.shuffle:
        random.shuffle(selected)

    for i, name in enumerate(selected):
        src = os.path.join(args.in_dir, name)
        dst = os.path.join(args.out_dir, "{0:06d}_{1}".format(i, name))
        shutil.copyfile(src, dst)

    print("input={0} output={1}".format(len(files), len(selected)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
