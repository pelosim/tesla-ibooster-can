#!/usr/bin/env python3
"""
Find the flat holds in a stroke capture and fit raw counts to millimetres.

The bench protocol is: hold still at known displacements. Each hold shows up as a
plateau -- a run of samples whose spread stays inside a tolerance. Detecting those
gives a clean value per known position, which is what a two-point fit needs. Reading
min/max off the whole capture would instead be dominated by overshoot and by the
end-stop pulse.

Usage:
    python3 plateaus.py logs/cal-idx1.log --id 39D --field le23
    python3 plateaus.py logs/cal-idx0.log --id 38E --field b3
"""
import argparse
import re
import sys

LINE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

FIELDS = {
    "le23": lambda d: d[2] | (d[3] << 8),
    "be23": lambda d: (d[2] << 8) | d[3],
    "b2": lambda d: d[2],
    "b3": lambda d: d[3],
    "b4": lambda d: d[4],
}


def load(path, want_id):
    out = []
    with open(path) as fh:
        for line in fh:
            m = LINE.match(line.strip())
            if not m:
                continue
            t, cid, payload = m.groups()
            if int(cid, 16) != want_id:
                continue
            out.append((float(t),
                        [int(payload[i:i + 2], 16)
                         for i in range(0, len(payload), 2)]))
    return out


def find_plateaus(times, vals, tol, min_dur):
    """Greedy: extend a run while max-min stays within tol."""
    plateaus, i, n = [], 0, len(vals)
    while i < n:
        lo = hi = vals[i]
        j = i + 1
        while j < n:
            nlo, nhi = min(lo, vals[j]), max(hi, vals[j])
            if nhi - nlo > tol:
                break
            lo, hi = nlo, nhi
            j += 1
        dur = times[j - 1] - times[i]
        if dur >= min_dur:
            seg = vals[i:j]
            plateaus.append({
                "t0": times[i], "t1": times[j - 1], "dur": dur,
                "n": len(seg), "mean": sum(seg) / len(seg),
                "min": min(seg), "max": max(seg),
            })
        i = j if j > i else i + 1
    return plateaus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--id", required=True)
    ap.add_argument("--field", default="le23", choices=sorted(FIELDS))
    ap.add_argument("--tol", type=int, default=40,
                    help="counts of spread still considered 'held'")
    ap.add_argument("--min-dur", type=float, default=2.0)
    args = ap.parse_args()

    frames = load(args.log, int(args.id, 16))
    if not frames:
        print(f"No {args.id} frames in {args.log}", file=sys.stderr)
        return 1

    fn = FIELDS[args.field]
    width = min(len(d) for _, d in frames)
    if max(int(c) for c in "234" if c.isdigit()) >= width and args.field == "le23":
        pass
    times = [t - frames[0][0] for t, _ in frames]
    vals = [fn(d) for _, d in frames]

    print(f"{len(frames)} frames of {args.id.upper()}, field {args.field}")
    print(f"raw range {min(vals)}..{max(vals)}\n")

    pls = find_plateaus(times, vals, args.tol, args.min_dur)
    print(f"Plateaus (tol +/-{args.tol} counts, min {args.min_dur}s):\n")
    print(f"{'#':>3} {'start':>8} {'end':>8} {'dur':>7} {'n':>6} "
          f"{'mean':>9} {'min':>7} {'max':>7}")
    for k, p in enumerate(pls):
        print(f"{k:3d} {p['t0']:8.2f} {p['t1']:8.2f} {p['dur']:7.2f} "
              f"{p['n']:6d} {p['mean']:9.1f} {p['min']:7d} {p['max']:7d}")

    if len(pls) >= 2:
        print("\nLongest holds (most likely the deliberate ones):")
        for p in sorted(pls, key=lambda x: -x["dur"])[:6]:
            print(f"  t={p['t0']:6.2f}..{p['t1']:6.2f}  {p['dur']:5.2f}s  "
                  f"mean {p['mean']:9.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
