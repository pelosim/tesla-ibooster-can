#!/usr/bin/env python3
"""
Regenerate every number in docs/DECODE.md that came from the 2026-08-11 pass.

The logs in logs/ are committed because they are the evidence behind DECODE.md.
This script is the other half of that: it turns them back into the claims, so a
claim can be re-checked rather than trusted.

What it verifies, in order:

  1. CRC-8 on the YAW bus            0x38E / 0x38F byte 0 carries no data
  2. 0x32D is static identity        identical across every power cycle
  3. Brake-flag thresholds           0x38E b6 and 0x38F b2, in millimetres
  4. The post-brake burst trigger    every burst follows a brake release
  5. Fits for the decoded fields     peak travel and hold time
  6. Correlation table               every burst byte, with uptime as a control

Three traps are wired into the checks themselves, because each one produced a
wrong answer first:

  * A checksum hypothesis is only tested by the frames that VARY. 0x33D sits at
    one constant payload 99.8% of the time, so a sum over its bytes "validates"
    on 99.87% of frames and means nothing. Check 1 reports how many distinct
    payloads it actually tested.
  * 0x31D/0x3AD b0:b1 is an uptime counter, and later events in a run had deeper
    and longer pedal applications. Uptime therefore impersonates a measurement of
    the brake event. It is excluded from the candidates and carried as a control
    column instead -- anything that tracks uptime as well as it tracks the event
    is not claimed.
  * n = 10, with far more candidate bytes than events, so a high r is cheap.
    Every reported correlation carries a permutation p-value.

Usage:
    python3 tools/events.py                 # all logs in logs/
    python3 tools/events.py --logs some/dir
    python3 tools/events.py --check crc     # one section
"""
import argparse
import math
import os
import random
import re
import sys
from collections import defaultdict

LINE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

# --- calibration, from DECODE.md -------------------------------------------
STROKE_PER_MM = 320.68          # 0x39D counts per mm
STROKE_ZERO = 3.3               # 0x39D counts at 0 mm
POS12_SCALE = 0.015207          # 0x38E 12-bit counts -> mm
POS12_OFFSET = -4.072
# The fault sentinel is 16354. Real travel reaches 13606 at the end stop and
# overshoots to 14070 on a fast strike, so a consumer's belt-and-braces "reject
# > 13700" is right for fault detection and WRONG here -- it clips real peaks.
SENTINEL_MIN = 14100

# --- analysis parameters ---------------------------------------------------
APPLY_THRESHOLD = 600           # 0x39D counts that count as "pedal pressed"
MERGE_GAP = 1.0                 # s below threshold before an application ends
BURST_WINDOW = 5.0              # s after a release in which to look for a burst
BURST_IDS = ("33D", "31D", "34D", "36D", "37D", "38D")
COUNTER_FIELDS = ("31D.b0", "31D.b1", "3AD.b0", "3AD.b1")  # uptime, not data
PERMUTATIONS = 20000

# 0x33D's at-rest payload. Not all-FF -- b0:b1 are 00, which is what made an
# earlier "all FF" filter silently keep every rest frame.
REST_33D = bytes.fromhex("0000FFFFFFFFFFFF")


def mm_stroke(counts):
    return (counts - STROKE_ZERO) / STROKE_PER_MM


def mm_pos12(pos):
    return POS12_SCALE * pos + POS12_OFFSET


def load(*paths):
    """-> {'39D': [(t, bytes), ...], ...}, sorted by time."""
    out = defaultdict(list)
    for path in paths:
        with open(path) as fh:
            for line in fh:
                m = LINE.match(line.strip())
                if not m:
                    continue
                t, cid, payload = m.groups()
                out[cid.upper()].append((float(t), bytes.fromhex(payload)))
    for cid in out:
        out[cid].sort(key=lambda r: r[0])
    return out


def discover_runs(logdir):
    """Group log files into runs.

    A run is one power cycle. Two-bus runs were captured as <name>-idx0 (YAW)
    and <name>-idx1 (vehicle); the adapter index is not stable across replugs,
    so which file is which bus is decided by CONTENT below, never by the name.
    """
    groups = defaultdict(list)
    for name in sorted(os.listdir(logdir)):
        if not name.endswith(".log"):
            continue
        path = os.path.join(logdir, name)
        if os.path.getsize(path) == 0:
            continue
        stem = name[:-4]
        key = re.sub(r"-idx\d$", "", stem)
        key = "busA/busB" if key in ("busA", "busB") else key
        groups[key].append(path)
    return dict(sorted(groups.items()))


# ---------------------------------------------------------------------------
# 1. CRC-8 on the YAW bus
# ---------------------------------------------------------------------------

def crc8(data, poly=0x1D, init=0x00, xorout=0x0A):
    """CRC-8/SAE-J1850. No reflection in or out."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc ^ xorout


def check_crc(data):
    print("=" * 78)
    print("1. CRC-8/SAE-J1850 over b1..b7  (poly 0x1D, init 0x00, xorout 0x0A)")
    print()
    ok = True
    for cid in ("38E", "38F"):
        frames = data.get(cid, [])
        if not frames:
            continue
        good = sum(1 for _, f in frames if crc8(f[1:]) == f[0])
        distinct = len({f[1:] for _, f in frames})
        pct = 100.0 * good / len(frames)
        ok &= good == len(frames)
        print(f"   {cid}: {good}/{len(frames)} frames = {pct:6.2f}%   "
              f"({distinct} distinct payloads tested)")
    print()
    print("   Same parameters for both IDs, so the CRC is not seeded from the ID.")
    print("   b0 therefore carries no data on either YAW message.")

    # The counter-example that keeps the method honest: on the vehicle bus this
    # scheme matches nothing, and an additive checksum matches only 0x39D.
    print()
    print("   For contrast, on the vehicle bus:")
    for cid in sorted(c for c in data if c not in ("38E", "38F")):
        frames = data[cid]
        crc_ok = sum(1 for _, f in frames if crc8(f[1:]) == f[0])
        sum_ok = sum(1 for _, f in frames if (sum(f[1:]) + 0xA0) & 0xFF == f[0])
        distinct = len({f[1:] for _, f in frames})
        note = ""
        if distinct == 1:
            note = "  <-- one payload only; any scheme can 'pass' here"
        print(f"     {cid}: CRC {100*crc_ok/len(frames):6.2f}%   "
              f"sum+0xA0 {100*sum_ok/len(frames):6.2f}%   "
              f"{distinct:3d} distinct{note}")
    return ok


# ---------------------------------------------------------------------------
# 2. 0x32D is static identity
# ---------------------------------------------------------------------------

def check_identity(runs):
    print("=" * 78)
    print("2. 0x32D -- static identity, multiplexed on b0")
    print()
    per_run = {}
    for name, data in runs.items():
        frames = data.get("32D", [])
        if frames:
            per_run[name] = {f[0]: f[1:] for _, f in frames}
    if len(per_run) < 2:
        print("   Need at least two runs to compare.")
        return False
    muxes = sorted(set().union(*(set(v) for v in per_run.values())))
    ok = True
    for mux in muxes:
        vals = {n: v[mux] for n, v in per_run.items() if mux in v}
        same = len(set(vals.values())) == 1
        ok &= same
        payload = " ".join(f"{b:02X}" for b in next(iter(vals.values())))
        print(f"   b0=0x{mux:02X}  {payload}   "
              f"{'IDENTICAL' if same else 'DIFFERS'} across {len(vals)} runs")
    print()
    print(f"   {len(per_run)} independent power cycles, "
          f"{'no' if ok else 'SOME'} byte differences.")
    return ok


# ---------------------------------------------------------------------------
# 3. Brake-flag thresholds
# ---------------------------------------------------------------------------

def edges(series):
    """-> {(from, to): [value at the first frame of the new state]}"""
    out = defaultdict(list)
    prev = None
    for _, state, value in series:
        if prev is not None and state != prev:
            out[(prev, state)].append(value)
        prev = state
    return out


def check_thresholds(runs):
    print("=" * 78)
    print("3. Brake flags -- thresholds in mm, pooled over every run")
    print()
    # (label, transition, series builder). Position comes from 0x38E in both
    # cases so the flag and the position it is compared against are in, or
    # interleaved with, the same message -- never split across buses.
    collected = defaultdict(list)
    for data in runs.values():
        pos = [(t, f[3] | ((f[4] & 0x0F) << 8)) for t, f in data.get("38E", [])]
        if len(pos) < 100:
            continue

        def pos_at(t):
            lo, hi = 0, len(pos) - 1
            if t < pos[0][0]:
                return None
            while lo < hi:
                mid = (lo + hi + 1) // 2
                lo, hi = (mid, hi) if pos[mid][0] <= t else (lo, mid - 1)
            return pos[lo][1]

        b6 = [(t, f[6], f[3] | ((f[4] & 0x0F) << 8)) for t, f in data["38E"]]
        for (a, b), vals in edges(b6).items():
            collected[("0x38E b6", f"{a} -> {b}")] += vals

        f38f = [(t, f[2], pos_at(t)) for t, f in data.get("38F", [])]
        f38f = [r for r in f38f if r[2] is not None]
        bit0 = [(t, s & 1, p) for t, s, p in f38f]
        for (a, b), vals in edges(bit0).items():
            collected[("0x38F b2 bit0", f"{a} -> {b}")] += vals
        db = [(t, 1 if s == 0xDB else 0, p) for t, s, p in f38f]
        for (a, b), vals in edges(db).items():
            collected[("0x38F b2 -> 0xDB", f"{a} -> {b}")] += vals

    print(f"   {'flag':22s} {'edge':8s} {'n':>3s}  {'mm range':>16s}")
    for (flag, edge), vals in sorted(collected.items()):
        mms = sorted(mm_pos12(v) for v in vals)
        print(f"   {flag:22s} {edge:8s} {len(vals):3d}  "
              f"{mms[0]:7.2f} - {mms[-1]:6.2f}")
    print()
    print("   0x38F is sampled at 49.8 Hz, so during a fast pedal return only one")
    print("   or two frames land in its release transition. Its OFF edge is")
    print("   rate-limited, not measured -- see the spread above. Do not quote it.")
    return True


# ---------------------------------------------------------------------------
# 4-6. Applications, bursts, fits, correlations
# ---------------------------------------------------------------------------

def applications(data):
    """Segment pedal applications from 0x39D stroke."""
    stroke = [(t, f[2] | (f[3] << 8)) for t, f in data.get("39D", [])]
    stroke = [(t, v) for t, v in stroke if v < SENTINEL_MIN]  # drop fault sentinel
    apps, cur, last_above = [], None, None
    for t, v in stroke:
        if v > APPLY_THRESHOLD:
            cur = [t, t, v] if cur is None else [cur[0], t, max(cur[2], v)]
            last_above = t
        elif cur and t - last_above > MERGE_GAP:
            apps.append(tuple(cur))
            cur = None
    if cur:
        apps.append(tuple(cur))

    out = []
    for t0, t1, peak in apps:
        seg = [(t, v) for t, v in stroke if t0 - 0.2 <= t <= t1 + 0.2]
        area = sum((seg[i + 1][0] - seg[i][0]) * max(0, seg[i][1] - 263)
                   for i in range(len(seg) - 1))
        rates = [(seg[i + 1][1] - seg[i][1]) / (seg[i + 1][0] - seg[i][0])
                 for i in range(len(seg) - 1) if seg[i + 1][0] > seg[i][0]]
        rates = [r for r in rates if abs(r) < 200000]  # drop resampling spikes
        out.append(dict(t0=t0, t1=t1, peak=peak, dur=t1 - t0,
                        integ=area / STROKE_PER_MM,
                        vmax=max(rates) / STROKE_PER_MM if rates else 0.0))
    return out


def bursts(data):
    """-> [(t, {cid: frame})] for complete bursts only."""
    groups = defaultdict(dict)
    for cid in BURST_IDS:
        for t, frame in data.get(cid, []):
            if cid == "33D" and frame == REST_33D:
                continue
            groups[round(t, 0)].setdefault(cid, frame)
    return [(t, g) for t, g in sorted(groups.items()) if len(g) >= 5]


def pair_runs(runs):
    """-> [record], each a burst joined to the application that triggered it."""
    recs = []
    for name, data in runs.items():
        apps = applications(data)
        for t, group in bursts(data):
            prior = [a for a in apps if 0 < t - a["t1"] < BURST_WINDOW]
            if not prior:
                continue
            rec = dict(prior[-1])
            rec["run"], rec["group"], rec["lag"] = name, group, t - prior[-1]["t1"]
            rec["uptime"] = (group["31D"][0] | (group["31D"][1] << 8)) / 10.0
            recs.append(rec)
    recs.sort(key=lambda r: r["peak"])
    return recs


BOOT_BURST_MAX_UPTIME = 10.0    # s; a burst this early is the boot one


def check_trigger(runs, recs):
    """A brake release triggers a burst -- with one documented exception.

    Each run also emits a burst at ~6.8 s of uptime with no pedal input at all.
    An earlier version of this claim said "no burst occurs without a release",
    which was simply not checked against the unpaired bursts. It is checked here.
    """
    print("=" * 78)
    print("4. The post-brake burst -- trigger")
    print()
    total_bursts = sum(len(bursts(d)) for d in runs.values())
    total_apps = sum(len(applications(d)) for d in runs.values())
    lags = [r["lag"] for r in recs]
    print(f"   complete bursts found        {total_bursts}")
    print(f"   pedal applications found     {total_apps}")
    print(f"   bursts after a release       {len(recs)}")
    if lags:
        print(f"   lag after release            {min(lags):.2f} - {max(lags):.2f} s")

    boot, unexplained = [], []
    for name, data in runs.items():
        apps = applications(data)
        for t, group in bursts(data):
            if any(0 < t - a["t1"] < BURST_WINDOW for a in apps):
                continue
            uptime = (group["31D"][0] | (group["31D"][1] << 8)) / 10.0
            (boot if uptime <= BOOT_BURST_MAX_UPTIME
             else unexplained).append((name, uptime))

    print(f"   boot-time bursts             {len(boot)}"
          f"   (no pedal input; ~{BOOT_BURST_MAX_UPTIME:.0f}s uptime cutoff)")
    for name, uptime in sorted(boot):
        print(f"       {name:14s} at {uptime:.1f} s of uptime")
    print(f"   unexplained bursts           {len(unexplained)}"
          f"{'   <-- trigger claim incomplete' if unexplained else ''}")
    for name, uptime in sorted(unexplained):
        print(f"       {name:14s} at {uptime:.1f} s of uptime")
    print()
    print("   Only the two runs whose capture covered ~6.8 s of uptime show the")
    print("   boot burst; stroke-sweep-1 started at 44 s and cal2 was mid-sweep.")
    return not unexplained and len(recs) > 0


def fit(xs, ys):
    """Least squares -> (slope, intercept, r, residuals)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return 0.0, my, 0.0, [0.0] * n
    slope = sxy / sxx
    icept = my - slope * mx
    return slope, icept, sxy / math.sqrt(sxx * syy), \
        [y - (slope * x + icept) for x, y in zip(xs, ys)]


def pearson(xs, ys):
    return fit(xs, ys)[2]


def perm_p(xs, ys, n=PERMUTATIONS):
    """Two-sided permutation p-value for |r|. Seeded, so runs are repeatable."""
    rng = random.Random(0)
    target = abs(pearson(xs, ys))
    shuffled = list(ys)
    hits = 0
    for _ in range(n):
        rng.shuffle(shuffled)
        if abs(pearson(xs, shuffled)) >= target:
            hits += 1
    return (hits + 1) / (n + 1)


def check_fits(recs):
    print("=" * 78)
    print("5. Decoded burst fields")
    print()
    peak_mm = [mm_stroke(r["peak"]) for r in recs]
    dur = [r["dur"] for r in recs]

    v38d = [r["group"]["38D"][5] | (r["group"]["38D"][6] << 8) for r in recs]
    slope, icept, r, res = fit(peak_mm, v38d)
    print(f"   0x38D b5:b6  = {slope:.1f} * mm {icept:+.1f}"
          f"    r = {r:.6f}   p = {perm_p(peak_mm, v38d):.5f}")
    print(f"                  worst residual {max(abs(e) for e in res) / slope:+.2f} mm"
          f"  (the ruler calibration is only good to about +-2 mm)")

    v37d = [r["group"]["37D"][0] | (r["group"]["37D"][1] << 8) for r in recs]
    slope, icept, r, res = fit(dur, v37d)
    print(f"   0x37D b0:b1  = {slope:.2f} * s {icept:+.1f}"
          f"     r = {r:.6f}   p = {perm_p(dur, v37d):.5f}")
    print(f"                  {slope:.2f} ticks/s is not a round number -- either a"
          f" ~{1000/slope:.0f} ms tick,")
    print(f"                  or the booster's own start/stop threshold differs"
          f" from {APPLY_THRESHOLD} counts.")

    print("                  Check 5b sweeps that threshold to tell the two apart.")

    bucket = [r["group"]["31D"][2] >> 4 for r in recs]
    r = pearson(dur, bucket)
    print()
    print(f"   0x31D b2>>4  bucket 1..7        r = {r:.3f}   "
          f"p = {perm_p(dur, bucket):.5f}")
    print(f"   {'held (s)':>10} {'bucket':>7} {'log2(s)+1':>10}")
    for d, b in sorted(zip(dur, bucket)):
        print(f"   {d:10.2f} {b:7d} {math.log2(d) + 1 if d > 0 else 0:10.2f}")
    print("   A log bucket is a diagnostic shape, not a control shape.")
    return True


def duration_sweep(runs, recs):
    """Refit 0x37D b0:b1 against duration measured at several thresholds.

    The point: if the slope barely moves, the booster's own threshold is low and
    the odd 27.5 ticks/s is a property of the TICK, not of our threshold choice.
    """
    print("=" * 78)
    print("5b. 0x37D b0:b1 -- how much does the measuring threshold matter?")
    print()
    v37d = [r["group"]["37D"][0] | (r["group"]["37D"][1] << 8) for r in recs]
    stroke_by_run = {n: [(t, f[2] | (f[3] << 8)) for t, f in d.get("39D", [])]
                     for n, d in runs.items()}
    print(f"   {'threshold':>10} {'ticks/s':>9} {'r':>10}")
    for th in (400, 600, 1000, 2000, 4000):
        durs = []
        for rec in recs:
            seg = [t for t, v in stroke_by_run[rec["run"]]
                   if rec["t0"] - 0.2 <= t <= rec["t1"] + 0.2 and v > th]
            durs.append(max(seg) - min(seg) if len(seg) > 1 else 0.0)
        slope, _, r, _ = fit(durs, v37d)
        print(f"   {th:10d} {slope:9.2f} {r:10.5f}")
    return True


def check_correlations(recs):
    print("=" * 78)
    print("6. Every burst byte vs every property of the application")
    print()
    metrics = [("peak", [mm_stroke(r["peak"]) for r in recs]),
               ("dur", [r["dur"] for r in recs]),
               ("integ", [r["integ"] for r in recs]),
               ("vmax", [r["vmax"] for r in recs]),
               ("uptime", [r["uptime"] for r in recs])]

    cands = {}
    for cid in BURST_IDS:
        width = len(recs[0]["group"][cid])
        for i in range(width):
            cands[f"{cid}.b{i}"] = [r["group"][cid][i] for r in recs]
            cands[f"{cid}.b{i}hi"] = [r["group"][cid][i] >> 4 for r in recs]
        for i in range(width - 1):
            cands[f"{cid}.b{i}:{i+1}LE"] = [
                r["group"][cid][i] | (r["group"][cid][i + 1] << 8) for r in recs]

    hdr = f"   {'field':16s}" + "".join(f"{m:>9s}" for m, _ in metrics) + "   flag"
    print(hdr)
    print("   " + "-" * (len(hdr) - 3))
    rows = []
    for name, vals in cands.items():
        if any(name.startswith(c) for c in COUNTER_FIELDS):
            continue                      # uptime counter, not event data
        # Drop constants only. An earlier cut here required 3+ distinct values,
        # which silently hid every two-value flag -- the exact class of field
        # that 0x38E b6 turned out to belong to.
        if len(set(vals)) < 2:
            continue
        rs = [pearson(mv, vals) for _, mv in metrics]
        best = max(abs(x) for x in rs[:4])
        # Keep anything that tracks the event OR that tracks uptime strongly --
        # the drift candidates are worth seeing, precisely so they can be
        # rejected on the record rather than quietly omitted.
        if best < 0.75 and abs(rs[4]) < 0.75:
            continue
        # If it tracks uptime about as well as it tracks the event, the ten
        # events cannot separate the two and nothing is claimed.
        if best < 0.75:
            flag = "DRIFT"            # tracks uptime, not the brake event
        elif abs(rs[4]) >= best - 0.10:
            flag = "CONFOUNDED"       # tracks both about equally; cannot separate
        else:
            flag = ""
        rows.append((best, name, rs, flag, vals))

    for best, name, rs, flag, vals in sorted(rows, reverse=True):
        print(f"   {name:16s}" + "".join(f"{x:9.2f}" for x in rs) + f"   {flag}")

    print()
    print("   uptime is a CONTROL column, not a result. Later events in a run had")
    print("   deeper and longer applications, so it impersonates a measurement.")
    print()
    print(f"   Permutation p-values (seeded, {PERMUTATIONS} iterations), "
          f"top unconfounded rows:")
    for best, name, rs, flag, vals in sorted(rows, reverse=True)[:6]:
        if flag:
            continue
        idx = max(range(4), key=lambda i: abs(rs[i]))
        metric, mv = metrics[idx]
        print(f"     {name:16s} vs {metric:7s} r = {rs[idx]:+.3f}   "
              f"p = {perm_p(mv, vals):.5f}")
    print()
    print(f"   n = {len(recs)}. With this many candidates a high r is cheap;")
    print("   below |r| ~ 0.9 treat anything here as a lead, not a result.")
    return True


def dump_table(recs):
    print("=" * 78)
    print("The paired events, raw")
    print()
    cols = ["0x38D b5:b6", "0x37D b0:b1", "0x31D b2>>4", "0x37D b5", "0x34D b5"]
    print(f"   {'run':12s} {'peak mm':>8} {'held s':>7} {'uptime s':>9} {'lag':>5}"
          + "".join(f"{c:>13s}" for c in cols))
    for r in recs:
        g = r["group"]
        vals = [g["38D"][5] | (g["38D"][6] << 8),
                g["37D"][0] | (g["37D"][1] << 8),
                g["31D"][2] >> 4, g["37D"][5], g["34D"][5]]
        print(f"   {r['run']:12s} {mm_stroke(r['peak']):8.2f} {r['dur']:7.2f} "
              f"{r['uptime']:9.1f} {r['lag']:5.2f}"
              + "".join(f"{v:13d}" for v in vals))


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=os.path.join(here, "logs"),
                    help="directory of candump logs (default: repo logs/)")
    ap.add_argument("--check", default="all",
                    choices=["all", "crc", "identity", "thresholds", "trigger",
                             "fits", "duration", "correlations", "table"])
    args = ap.parse_args()

    if not os.path.isdir(args.logs):
        print(f"No such directory: {args.logs}", file=sys.stderr)
        return 1

    run_paths = discover_runs(args.logs)
    runs = {name: load(*paths) for name, paths in run_paths.items()}
    runs = {n: d for n, d in runs.items() if d}
    if not runs:
        print(f"No frames parsed from {args.logs}", file=sys.stderr)
        return 1

    every = defaultdict(list)
    for data in runs.values():
        for cid, frames in data.items():
            every[cid] += frames

    total = sum(len(v) for v in every.values())
    print(f"{len(runs)} runs, {len(every)} IDs, {total} frames")
    for name, paths in run_paths.items():
        if name in runs:
            print(f"   {name:14s} {', '.join(os.path.basename(p) for p in paths)}")
    print()

    recs = pair_runs(runs)
    want = args.check
    results = {}

    if want in ("all", "crc"):
        results["crc"] = check_crc(every)
        print()
    if want in ("all", "identity"):
        results["identity"] = check_identity(runs)
        print()
    if want in ("all", "thresholds"):
        results["thresholds"] = check_thresholds(runs)
        print()
    if want in ("all", "trigger"):
        results["trigger"] = check_trigger(runs, recs)
        print()

    if not recs and want in ("all", "fits", "duration", "correlations", "table"):
        print("No burst/application pairs found -- nothing to fit.", file=sys.stderr)
        return 1

    if want in ("all", "fits"):
        check_fits(recs)
        print()
    if want in ("all", "duration"):
        duration_sweep(runs, recs)
        print()
    if want in ("all", "correlations"):
        check_correlations(recs)
        print()
    if want in ("all", "table"):
        dump_table(recs)
        print()

    failed = [k for k, v in results.items() if not v]
    if failed:
        print(f"FAILED: {', '.join(failed)} -- DECODE.md and the logs disagree.",
              file=sys.stderr)
        return 1
    if results:
        print(f"All {len(results)} verifiable checks agree with docs/DECODE.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
