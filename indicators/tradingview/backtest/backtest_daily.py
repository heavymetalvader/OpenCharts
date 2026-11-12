"""
Daily-resolution backtest of the GEX × Strat 0DTE credit-spread rules.

What it tests (everything known at the 9:30 open, no look-ahead):
  * Strike rule: short strike = open ± m × 1σ day move from VIX1D, 10-wide.
  * Higher-timeframe Strat filters: yesterday's daily Strat combo and FTFC of
    today's open vs. the week / month / quarter open.
  * Outcome: settles at the SPX close (0DTE, held to expiry, no management).

What it can NOT test: the 5-minute combos, VWAP/OR filters, or GEX levels
(no free intraday or historical-GEX data). Credits are Black-Scholes with flat
VIX1D vol, so they are an estimate (real put skew pays more for puts).

Data: Cboe daily SPX and VIX1D (free, delayed):
  https://cdn-api.cboe.com/api/global/delayed_quotes/charts/historical/_SPX.json
  https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX1D_History.csv

Usage: python backtest_daily.py SPX.json VIX1D_History.csv
"""
import json
import math
import sys

import numpy as np
import pandas as pd

WIDTH = 10.0
STEP = 5.0


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, sd, call):
    """Undiscounted Black-Scholes with total stdev `sd` (fraction)."""
    if sd <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if call:
        return S * ncdf(d1) - K * ncdf(d2)
    return K * ncdf(-d2) - S * ncdf(-d1)


def strat_type(h, l, ph, pl):
    if h > ph and l < pl:
        return 3
    if h > ph:
        return 2
    if l < pl:
        return -2
    return 1


def load(spx_path, vix_path):
    d = json.load(open(spx_path))["data"]
    spx = pd.DataFrame(d)
    spx["date"] = pd.to_datetime(spx["date"])
    for c in ["open", "high", "low", "close"]:
        spx[c] = spx[c].astype(float)
    spx = spx[spx["open"] > 0].set_index("date")[["open", "high", "low", "close"]]

    v = pd.read_csv(vix_path)
    v["DATE"] = pd.to_datetime(v["DATE"], format="%m/%d/%Y")
    v = v.set_index("DATE").rename(columns=str.lower)
    v["prev_close"] = v["close"].shift(1)
    # VIX1D's first prints of a day can be stale; use open when the bar has a
    # real range, otherwise yesterday's close.
    flat = (v["high"] == v["low"])
    v["iv"] = np.where(flat, v["prev_close"], v["open"])
    return spx.join(v[["iv", "prev_close"]], how="inner").dropna()


def build(df, full_spx):
    s = full_spx.copy()
    s["t"] = [np.nan] + [strat_type(s.high.iloc[i], s.low.iloc[i], s.high.iloc[i - 1], s.low.iloc[i - 1]) for i in range(1, len(s))]
    s["t1"], s["t2"], s["t3"] = s["t"].shift(1), s["t"].shift(2), s["t"].shift(3)
    # Period opens known at today's open
    s["wk_open"] = s.groupby(s.index.to_period("W"))["open"].transform("first")
    s["mo_open"] = s.groupby(s.index.to_period("M"))["open"].transform("first")
    s["q_open"] = s.groupby(s.index.to_period("Q"))["open"].transform("first")
    s["prev_close"] = s["close"].shift(1)
    df = df.join(s[["t1", "t2", "t3", "wk_open", "mo_open", "q_open"]], how="left")
    df["prev_spx_close"] = s["prev_close"]

    def combo(r):
        a, b, c = r.t3, r.t2, r.t1   # c = yesterday (the trigger bar)
        if b == 1 and abs(a) in (2, 3) and c == 2:
            return 1
        if b == 1 and abs(a) in (2, 3) and c == -2:
            return -1
        if a in (3, 1) and b == -2 and c == 2:
            return 1
        if a in (3, 1) and b == 2 and c == -2:
            return -1
        if b == -2 and c == 2:
            return 1
        if b == 2 and c == -2:
            return -1
        return 0

    df["combo"] = df.apply(combo, axis=1)
    sgn = lambda x: np.sign(x)
    # Today's open vs the week open is 0 on Mondays (open IS the week open);
    # that's what FTFC sees at 9:30.
    df["ftfc"] = sgn(df.open - df.wk_open) + sgn(df.open - df.mo_open) + sgn(df.open - df.q_open)
    df["gap"] = sgn(df.open - df.prev_spx_close)
    return df


def trades(df, m):
    rows = []
    for dt, r in df.iterrows():
        S, sd = r.open, r.iv / 100 / math.sqrt(252)
        em = S * sd
        kp = math.floor((S - m * em) / STEP) * STEP
        kc = math.ceil((S + m * em) / STEP) * STEP
        cr_p = bs(S, kp, sd, False) - bs(S, kp - WIDTH, sd, False)
        cr_c = bs(S, kc, sd, True) - bs(S, kc + WIDTH, sd, True)
        loss_p = min(WIDTH, max(0.0, kp - r.close))
        loss_c = min(WIDTH, max(0.0, r.close - kc))
        rows.append(dict(
            date=dt, em=em,
            pcs=cr_p - loss_p, ccs=cr_c - loss_c,
            pcs_breach=r.close < kp, ccs_breach=r.close > kc,
            pcs_touch=r.low <= kp, ccs_touch=r.high >= kc,
            cr_p=cr_p, cr_c=cr_c,
            combo=r.combo, ftfc=r.ftfc, gap=r.gap,
            up=r.close > r.open,
        ))
    return pd.DataFrame(rows).set_index("date")


def summarize(t, side, mask, label):
    x = t[mask]
    if len(x) == 0:
        return None
    pnl = x[side]
    cr = x["cr_p" if side == "pcs" else "cr_c"]
    return dict(
        filter=label, side=side.upper(), n=len(x),
        win=f"{100 * (1 - x[side + '_breach'].mean()):.1f}%",
        touched=f"{100 * x[side + '_touch'].mean():.1f}%",
        avg_credit=round(cr.mean(), 2),
        ev_per_spread=round(pnl.mean() * 100, 0),     # $ per 1-lot (SPX ×100)
        total=round(pnl.sum() * 100, 0),
        worst_day=round(pnl.min() * 100, 0),
        up_close=f"{100 * x['up'].mean():.1f}%",
    )


def main():
    spx_path, vix_path = sys.argv[1], sys.argv[2]
    d = json.load(open(spx_path))["data"]
    full = pd.DataFrame(d)
    full["date"] = pd.to_datetime(full["date"])
    for c in ["open", "high", "low", "close"]:
        full[c] = full[c].astype(float)
    full = full[full["open"] > 0].set_index("date")

    df = build(load(spx_path, vix_path), full)
    print(f"Sample: {df.index[0].date()} → {df.index[-1].date()}  ({len(df)} sessions)\n")

    pd.set_option("display.width", 200)
    for m in (0.75, 1.0, 1.25):
        t = trades(df, m)
        out = []
        filters = [
            ("ALL DAYS (baseline)", pd.Series(True, index=t.index)),
            ("bull combo yday", t.combo == 1),
            ("bear combo yday", t.combo == -1),
            ("FTFC +3 (W/M/Q up)", t.ftfc == 3),
            ("FTFC -3 (W/M/Q down)", t.ftfc == -3),
            ("FTFC ≥ +2", t.ftfc >= 2),
            ("FTFC ≤ -2", t.ftfc <= -2),
            ("bull combo + FTFC ≥ +2", (t.combo == 1) & (t.ftfc >= 2)),
            ("bear combo + FTFC ≤ -2", (t.combo == -1) & (t.ftfc <= -2)),
        ]
        for label, mask in filters:
            for side in ("pcs", "ccs"):
                s = summarize(t, side, mask, label)
                if s:
                    out.append(s)
        print(f"═══ Short strike = open ± {m}σ (VIX1D), {WIDTH:.0f}-wide, held to close ═══")
        print(pd.DataFrame(out).to_string(index=False))
        # Iron condor = both sides
        ic = t.pcs + t.ccs
        print(f"  IRON CONDOR all days: n={len(t)}  both-sides-safe={100 * (~t.pcs_breach & ~t.ccs_breach).mean():.1f}%  EV=${ic.mean() * 100:.0f}  worst=${ic.min() * 100:.0f}")
        print(f"  Realized |close-open| / 1σ EM: median {np.median(abs(df.close.values - df.open.values) / t.em.values):.2f}  (1.00 = VIX1D exactly right)\n")


if __name__ == "__main__":
    main()
