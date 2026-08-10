#!/usr/bin/env python3
"""
Find physical signals in a candump log by shape, not by range.

A CRC or alive-counter spans 00..FF but jumps randomly frame to frame. A pedal
position spans a range and moves *smoothly*. Ranking by range alone flags every
CRC in the capture; ranking by smoothness finds the actual signal.

    smoothness = mean(|delta between consecutive frames|) / range

Low is smooth. CRCs land near 0.3-0.5, physical signals well under 0.05.

Usage:
    python3 analyze.py logs/stroke-sweep-1.log
    python3 analyze.py logs/stroke-sweep-1.log --id 39D
"""
import argparse
import re
import sys
from collections import defaultdict

LINE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def load(path):
    """-> {can_id: [(t, [bytes]), ...]}"""
    out = defaultdict(list)
    with open(path) as fh:
        for line in fh:
            m = LINE.match(line.strip())
            if not m:
                continue
            t, cid, payload = m.groups()
            data = [int(payload[i:i + 2], 16) for i in range(0, len(payload), 2)]
            out[int(cid, 16)].append((float(t), data))
    return out


def series_stats(vals):
    """-> (min, max, range, smoothness, activity)

    activity = fraction of consecutive frames where the value changed at all.
    Without it, a field that sits at FF and jumps rarely scores as very "smooth"
    (small mean delta over a big range) and outranks the real signal -- which is
    exactly what 0x33D did on the first sweep.
    """
    lo, hi = min(vals), max(vals)
    rng = hi - lo
    if rng == 0 or len(vals) < 3:
        return lo, hi, rng, None, 0.0
    deltas = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    activity = sum(1 for d in deltas if d) / len(deltas)
    return lo, hi, rng, (sum(deltas) / len(deltas)) / rng, activity


def plot(vals, times, width=72, height=11):
    """ASCII time series so the sweep shape is visible: up, holds, down."""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return ["(flat)"]
    t0, t1 = times[0], times[-1]
    span = (t1 - t0) or 1.0
    buckets = [[] for _ in range(width)]
    for t, v in zip(times, vals):
        buckets[min(width - 1, int((t - t0) / span * width))].append(v)
    col = [sum(b) / len(b) if b else None for b in buckets]

    rows = []
    for r in range(height):
        hi_r = hi - (hi - lo) * r / height
        lo_r = hi - (hi - lo) * (r + 1) / height
        line = "".join("#" if c is not None and lo_r <= c <= hi_r else " "
                       for c in col)
        rows.append(f"{hi_r:7.0f} |{line}")
    rows.append(f"{'':7} +{'-' * width}")
    rows.append(f"{'':8}{t0 - t0:<6.0f}s{' ' * (width - 14)}{t1 - t0:.0f}s")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--id", help="plot this ID's candidate bytes (hex)")
    ap.add_argument("--min-range", type=int, default=8)
    ap.add_argument("--max-smooth", type=float, default=0.15)
    ap.add_argument("--min-activity", type=float, default=0.20,
                    help="drop fields that rarely change at all; without this a "
                         "field parked at FF outranks the real signal")
    args = ap.parse_args()

    data = load(args.log)
    if not data:
        print("No frames parsed.", file=sys.stderr)
        return 1

    print(f"{len(data)} IDs, "
          f"{sum(len(v) for v in data.values())} frames\n")

    cands = []
    for cid, frames in data.items():
        if len(frames) < 5:
            continue
        times = [t for t, _ in frames]
        width = min(len(d) for _, d in frames)

        # single bytes
        for i in range(width):
            vals = [d[i] for _, d in frames]
            lo, hi, rng, sm, act = series_stats(vals)
            if rng >= args.min_range and sm is not None and act >= args.min_activity:
                cands.append((sm, cid, f"b{i}", lo, hi, rng, act, vals, times))

        # 16-bit pairs, both endiannesses
        for i in range(width - 1):
            for label, fn in (("LE", lambda a, b: a | (b << 8)),
                              ("BE", lambda a, b: (a << 8) | b)):
                vals = [fn(d[i], d[i + 1]) for _, d in frames]
                lo, hi, rng, sm, act = series_stats(vals)
                if rng >= args.min_range and sm is not None and act >= args.min_activity:
                    cands.append((sm, cid, f"b{i}:{i+1}{label}",
                                  lo, hi, rng, act, vals, times))

    cands.sort(key=lambda c: c[0])

    print("Ranked by smoothness (low = physical signal, high = CRC/counter):\n")
    print(f"{'smooth':>7} {'active':>7}  {'ID':>4} {'field':>10} "
          f"{'min':>7} {'max':>7} {'range':>7}")
    shown = 0
    for sm, cid, field, lo, hi, rng, act, _, _ in cands:
        if sm > args.max_smooth and shown >= 12:
            break
        flag = "  <== SMOOTH" if sm < 0.05 else ""
        print(f"{sm:7.3f} {act:7.2f}  {cid:4X} {field:>10} "
              f"{lo:7d} {hi:7d} {rng:7d}{flag}")
        shown += 1
        if shown >= 25:
            break

    if args.id:
        want = int(args.id, 16)
        print(f"\n\n=== {want:03X} candidate traces ===")
        for sm, cid, field, lo, hi, rng, act, vals, times in cands:
            if cid != want or sm > args.max_smooth:
                continue
            print(f"\n{field}  range {lo}..{hi}  smoothness {sm:.3f}  "
                  f"activity {act:.2f}")
            for row in plot(vals, times):
                print(row)
    else:
        best = next((c for c in cands if c[0] < 0.05), None)
        if best:
            sm, cid, field, lo, hi, rng, act, vals, times = best
            print(f"\n\n=== best candidate: {cid:03X} {field} ===")
            for row in plot(vals, times):
                print(row)
            print(f"\nRe-run with --id {cid:03X} to see every smooth field on that ID.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
