"""
Snapshot today's SPX 0DTE chain from Cboe (free, ~15 min delayed) and measure,
for the IC lab's pricing model:
  * atm_ratio = real 0DTE ATM 1σ  ÷  (VIX1D-implied 1σ for the minutes left)
  * skew curve IV(K)/ATM vs z = ln(K/F)/ATM σ  (fit a, b per side)
  * real 10-wide / 5-wide vertical mids at ~10/15/20/30Δ vs the model

Usage: python -I snapshot_0dte.py OUT_DIR [EXPIRY_YYMMDD]
Writes OUT_DIR/snap_HHMM.json and prints a summary.
"""
import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CHAIN = "https://cdn-api.cboe.com/api/global/delayed_quotes/options/_SPX.json"
VIX1D = "https://cdn-api.cboe.com/api/global/delayed_quotes/charts/intraday/_VIX1D.json"


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(F, K, sd, call):
    d1 = (math.log(F / K) + sd * sd / 2) / sd
    d2 = d1 - sd
    return F * N(d1) - K * N(d2) if call else K * N(-d2) - F * N(-d1)


def implied_sd(F, px, K, call):
    lo, hi = 1e-6, 0.3
    for _ in range(120):
        m = (lo + hi) / 2
        if bs(F, K, m, call) > px:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    chain = get(CHAIN)
    data = chain["data"]
    # chain timestamp is UTC; intraday chart datetimes are US/Eastern
    ts = datetime.strptime(chain["timestamp"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/New_York"))
    exp = sys.argv[2] if len(sys.argv) > 2 else ts.strftime("%y%m%d")
    ch = {}
    for o in data["options"]:
        m = re.match(r"SPXW(\d{6})([CP])(\d{8})", o["option"])
        if m and m.group(1) == exp and o["bid"] is not None and o["ask"] is not None:
            ch[(m.group(2), int(m.group(3)) / 1000)] = o
    if not ch:
        print("no options for expiry", exp)
        return
    mid = lambda o: (o["bid"] + o["ask"]) / 2
    S = data["current_price"]
    ks = sorted({k for (_, k) in ch})
    atmK = min((k for k in ks if ("C", k) in ch and ("P", k) in ch), key=lambda k: abs(k - S))
    F = atmK + mid(ch[("C", atmK)]) - mid(ch[("P", atmK)])
    sd_atm = (implied_sd(F, mid(ch[("C", atmK)]), atmK, True) + implied_sd(F, mid(ch[("P", atmK)]), atmK, False)) / 2

    mins_left = max(1, (16 * 60) - (ts.hour * 60 + ts.minute))
    vix = get(VIX1D)["data"]
    hhmm = ts.strftime("%H:%M")
    day = ts.strftime("%Y-%m-%d")
    vx = [r for r in vix if r["datetime"][:10] == day and r["datetime"][11:16] <= hhmm]
    v1d = vx[-1]["price"]["close"] if vx else None
    model_sd = v1d / 100 * math.sqrt(mins_left / (252 * 390)) if v1d else None
    ratio = sd_atm / model_sd if model_sd else None

    pts = []
    for (cp, k), o in ch.items():
        if (cp == "P") != (k < F) or o["bid"] <= 0:
            continue
        z = math.log(k / F) / sd_atm
        if abs(z) > 3.5:
            continue
        pts.append(dict(z=z, r=implied_sd(F, mid(o), k, cp == "C") / sd_atm, k=k, cp=cp,
                        bid=o["bid"], ask=o["ask"], delta=o.get("delta")))

    def fit(side):
        xs = [(p["z"], p["r"] - 1) for p in pts if (p["z"] < 0) == (side == "P") and abs(p["z"]) > 0.05]
        if len(xs) < 3:
            return None
        s11 = sum(z * z for z, _ in xs); s12 = sum(z ** 3 for z, _ in xs); s22 = sum(z ** 4 for z, _ in xs)
        t1 = sum(z * y for z, y in xs); t2 = sum(z * z * y for z, y in xs)
        det = s11 * s22 - s12 * s12
        return ((t1 * s22 - t2 * s12) / det, (s11 * t2 - s12 * t1) / det)

    # real vertical mids near target deltas (5- and 10-wide)
    verts = []
    for cp in ("P", "C"):
        for target in (0.10, 0.15, 0.20, 0.30):
            cands = [(k, o) for (c, k), o in ch.items() if c == cp and o.get("delta") is not None]
            if not cands:
                continue
            k, o = min(cands, key=lambda ko: abs(abs(ko[1]["delta"]) - target))
            for w in (5, 10):
                kl = k - w if cp == "P" else k + w
                ol = ch.get((cp, kl))
                if ol:
                    verts.append(dict(side=cp, target=target, short=k, long=kl, width=w,
                                      delta=o["delta"], mid=mid(o) - mid(ol), natural=o["bid"] - ol["ask"]))

    if not (9 * 60 + 30 <= ts.hour * 60 + ts.minute < 16 * 60):
        print("market closed at quote time", ts, "- ratio not meaningful")
    res = dict(quote_time=str(ts), expiry=exp, spot=S, forward=F, mins_left=mins_left,
               vix1d=v1d, atm_sd=sd_atm, atm_pts=sd_atm * F, atm_ratio=ratio,
               put_skew=fit("P"), call_skew=fit("C"), verticals=verts, points=pts)
    path = os.path.join(out, f"snap_{ts.strftime('%H%M')}.json")
    json.dump(res, open(path, "w"), indent=1)
    print(f"{ts}  exp {exp}  spot {S:.2f}  mins_left {mins_left}  VIX1D {v1d}  "
          f"ATM 1σ {sd_atm * F:.1f} pts  ATM/VIX1D ratio {ratio if ratio is None else round(ratio, 3)}")
    print("  put skew a,b =", res["put_skew"], " call skew a,b =", res["call_skew"])
    for v in verts:
        print(f"  {v['side']} {v['short']:.0f}/{v['long']:.0f} Δ{abs(v['delta']):.2f}  mid {v['mid']:.2f}  natural {v['natural']:.2f}")
    print("saved", path)


if __name__ == "__main__":
    main()
