# GEX × The Strat: 0DTE SPX Credit Spread Toolkit (TradingView)

`gex_strat_0dte.pine` is a Pine Script v6 overlay. It combines dealer gamma
positioning, The Strat, and the intraday context that matters for 0DTE SPX
credit spreads.

## Install

1. TradingView → Pine Editor → **New** → paste `gex_strat_0dte.pine` → **Add to chart**.
2. Use it on an **SPX** chart (1–15m works best; 5m is the sweet spot). SPY, ES and XSP
   also work: SPX levels are auto-scaled by the live ratio to SPX.
3. Every morning, paste one line into **📋 Paste levels** in the settings:

   ```
   CW=7550; PW=7500; ZG=7555; N=7600,7475,7450,7400
   ```

   `CW` = call wall, `PW` = put wall, `ZG` = zero gamma / flip, `HVL` = vol trigger,
   `N` = extra nodes. The keys can go in any order. Anything you paste overrides the
   individual fields. Get the numbers from your GEX provider (SpotGamma, Quantwheel,
   etc.). Pine can't read option chains, so it can't compute GEX itself.

## What's on the chart

| Element | Meaning |
|---|---|
| Red / green / yellow solid lines | Call Wall / Put Wall / Zero-γ flip (today only) |
| Red background tint | Price below the flip, so you're in **negative gamma**: dealers amplify moves |
| Purple bands | ±1σ expected move for the day from **VIX1D** (falls back to VIX) |
| Orange lines | Opening range (5/15/30/60m) |
| Grey lines | Prior-day RTH high / low / close |
| Blue line | Session VWAP (weighted by SPY volume, since SPX has none) |
| Bar colors | Strat types: yellow = 1, purple = 3, green = 2U, red = 2D |
| Teal / red step lines | Inside-bar 2U / 2D triggers |
| Small labels | Strat combos: 2-1-2, 3-1-2, 2-2, 3-2-2, 1-2-2 RevStrat |
| **PCS / CCS triangles** | A Strat combo that agrees with FTFC, inside the entry window, on the right side of the wall |
| Dotted lines | Suggested short strikes |
| Orange tint | Late-day gamma danger zone (default 15:00–16:00 ET) |

## The engine

**Score (−10 … +10)** = FTFC (±5) + VWAP side (±1) + opening-range break (±1)
+ side of the flip (±1) + a fresh Strat combo (±2).

| Condition | Bias |
|---|---|
| score ≥ threshold (default 3; **+2 more in negative γ**) | BULL PUT SPREAD |
| score ≤ −threshold | BEAR CALL SPREAD |
| positive γ, price between the walls, \|score\| ≤ 2 | IRON CONDOR |
| otherwise / outside the entry window | STAND ASIDE / WAIT |

**Strike suggestion:** the short strike is the *farther* of
(a) `N × remaining 1σ move` from price and (b) the GEX wall plus a buffer, rounded
to the strike increment. The remaining 1σ shrinks with √(time left in the session),
so strikes tighten as theta works for you.

**Defense:** enter your live short strikes and the indicator draws them, shows
your cushion, and fires an alert when price gets within N points.

## Backtest (daily, 2022-05 → 2026-11, 1,126 sessions)

`backtest/backtest_daily.py` replays the rules with free Cboe daily SPX and VIX1D
data. Each day it enters at the 9:30 open with 10-wide spreads and holds to the
close. Only information available at the open is used.

| 1σ VIX1D short strike | n | Win (closed OTM) | EV / spread* |
|---|---|---|---|
| PCS, every day | 1126 | 89.1% | +$29 |
| CCS, every day | 1126 | 88.8% | +$33 |
| **PCS, bullish daily combo yesterday + W/M/Q FTFC ≥ +2** | 105 | **94.3%** | **+$57** |
| **CCS, bullish daily combo yesterday** | 190 | **82.6%** | **−$9** |
| Iron condor, every day | 1126 | 77.9% both sides | +$62 |

\*Credits come from Black-Scholes with flat VIX1D vol and no commissions. Treat the
dollar figures as rough; the win rates are the reliable numbers.

What it shows:
- **VIX1D overprices the day's move.** The median realized open-to-close move was
  0.61σ, and that gap is the whole edge in selling 0DTE.
- **The edge is thin.** At 1σ you need about 88% wins to break even, and you get 89%.
  At $0.10 per spread in slippage/fees the baseline PCS drops to about +$19.
- **Strat + FTFC helps the bull put side.** It cut losses from 11% to 6% of trades
  (6/105, p ≈ 0.05). That's encouraging but not proven: it's a small sample, and I
  tried many filters.
- **Don't sell call spreads after a bullish daily combo.** That was the weakest trade
  in every variant, so the indicator now blocks CCS on those days.
- **Bearish Strat signals added nothing.** The sample period mostly trended up.
- **Not tested:** the 5-minute combos, VWAP/OR, and GEX levels. There's no free
  intraday SPX history or historical GEX.

Reproduce:
```
curl -sL -o SPX.json https://cdn-api.cboe.com/api/global/delayed_quotes/charts/historical/_SPX.json
curl -sL -o VIX1D.csv https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX1D_History.csv
python backtest/backtest_daily.py SPX.json VIX1D.csv
```

## Alerts

Create an alert → condition: this indicator → either a named condition (PCS/CCS
setup, γ flip up/down, short put/call threatened, Strat combos) or
**"Any alert() function call"**. The second option sends messages that include the
suggested strikes and the score.

## Caveats (read these)

- GEX levels are a snapshot. 0DTE positioning shifts intraday, so refresh them midday if your provider updates.
- VIX1D needs CBOE index data on your TradingView plan. Without it, the script falls back to VIX, which **overstates** the 0DTE move.
- Strat signals print only on **bar close**. On a live bar, the bar type can change until the bar closes.
- This is a decision aid, not a signal service. Size so that a max loss on the spread doesn't hurt. Not financial advice.
