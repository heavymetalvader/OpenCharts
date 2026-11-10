# GEX × The Strat: 0DTE SPX Credit Spread Toolkit (TradingView)

`gex_strat_0dte.pine` is a Pine Script v6 overlay. It combines dealer gamma
positioning, The Strat, and the intraday context that matters for 0DTE SPX
credit spreads.

## Install

1. TradingView → Pine Editor → **New** → paste `gex_strat_0dte.pine` → **Add to chart**.
2. Use it on an **SPX** chart (1–15m works best; 5m is the sweet spot). SPY, ES and XSP
   also work: SPX levels are auto-scaled by the live ratio to SPX.
3. Every morning, open the settings and paste in that day's **Call Wall, Put Wall and
   Zero Gamma**, plus any extra nodes, from your GEX provider (SpotGamma, Quantwheel,
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
