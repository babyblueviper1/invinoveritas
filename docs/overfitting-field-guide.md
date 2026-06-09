# The Overfitting Field Guide for Trading Bots

*Why your backtest looks great and your live bot bleeds — and how to test for it before you risk money.*

Most trading strategies don't fail because the model is bad. They fail because the backtest was
**curve-fit**: the strategy memorized the past instead of finding a repeatable edge. This guide covers
the three statistical tests that catch it, in plain language, with the exact failure modes we've hit
running our own live bot. At the end there's a free tool that runs all three on your returns.

---

## The core problem: you tried more than one thing

If you tested 50 parameter combinations and picked the best one, your "best Sharpe" is not what it
seems. The maximum of 50 noisy numbers is biased upward — *some* combination will look great by pure
luck. This is the **multiple-testing problem**, and it's the single biggest reason backtests don't
survive contact with live markets.

Honest validation means asking: *given how many things I tried, is this result still surprising?*

## Test 1 — Deflated Sharpe Ratio (DSR)

The DSR (Bailey & López de Prado) haircuts your Sharpe ratio for (a) how many variants you tried,
(b) how short your sample is, and (c) how non-normal your returns are (fat tails, skew). A strategy
with in-sample Sharpe 2.0 after trying 200 configs on 6 months of data can easily deflate to ~0 —
meaning the evidence is consistent with *no edge at all*.

**Rule of thumb:** if you can't state how many variants you tried, your Sharpe is unauditable.
Pre-register the grid before you run it.

## Test 2 — Permutation test (MCPT)

Shuffle the data (or trade ordering) thousands of times and re-run the strategy on each shuffled
series. This builds the *null distribution*: what your metric looks like when there is provably no
signal. If your real result isn't clearly outside that distribution (p < 0.05 at minimum; we use
p < 0.01 for anything that touches live capital), your edge is indistinguishable from luck.

We've killed more of our own strategies with this test than with any other. A strategy of ours that
passed in-sample Sharpe +1.13 on the full history failed MCPT on fresh data (p = 0.568) — the second
half of the sample had decayed to −1.02. We retired it the same day. Past-validated does not mean
currently-valid.

## Test 3 — Out-of-sample decay (purged k-fold)

Split your history into k chronological folds, validate on each fold using only data that came
before it (purging any overlap so information can't leak). Then look at the *trend across folds*:
a real edge holds roughly steady; a curve-fit one decays monotonically toward zero — it tracked a
regime, not a mechanism. One of ours showed fold-correlation ρ = −1.00 (perfectly monotonic decay).
The headline backtest said +349% projected; the folds said don't extrapolate. The folds were right.

## The failure modes that don't show up in any formula

- **Survivorship bias:** backtesting on coins/stocks that are liquid *today* silently excludes the
  ones that died. We watched a cross-sectional momentum strategy go from Sharpe 1.44 (p = 0.002) to
  Sharpe 0.07 (p = 0.42) when delisted assets were added back. The entire edge was survivorship.
- **Fee/fill realism:** an edge of 3 bps per trade is fiction if your venue costs 5.5 bps per side.
  Price your *actual* venue's fees into signal generation, not as an afterthought. Maker-fill
  assumptions are the same trap: we measured 11% real dual-leg fill on a strategy backtested at 99.5%.
- **Regime tracking:** a strategy validated across one regime (one trending year, one vol environment)
  is a bet that the regime continues, not evidence of an edge. Demand positive performance in
  *multiple disjoint time windows* before believing it.
- **Stale validation:** edges decay. Whatever gate a strategy passed at birth, re-run it on fresh
  data periodically — automatically if real money is on the line.

## Run all three on your strategy, free

We built these gates for our own live bot, then opened them up:

- **[EdgeProof](https://api.babyblueviper.com/edgeproof)** — paste your strategy's realized returns
  (never your code or signals — we don't want them), get a verdict: `likely_real / borderline /
  overfit`, backed by DSR + permutation test + purged k-fold decay. Free in the browser.
- Programmatic version for agents/CI: `POST /validate` ([docs](https://api.babyblueviper.com/llms.txt)).

## Why trust the operators of yet another tool?

You don't have to. Every verdict our governance gate issues is **signed and published before its
outcome is known**, and outcomes settle on a public on-chain account — wins *and* losses:

- Public track record: [`/ledger.txt`](https://api.babyblueviper.com/ledger.txt) (human-readable),
  [`/ledger`](https://api.babyblueviper.com/ledger) (signed Nostr events, verifiable against our
  published key — standard NIP-01, check it yourself).
- Verify any proof we've issued, trustlessly and free:
  [`POST /verify-proof`](https://api.babyblueviper.com/llms.txt).

The same statistical gates in this guide are the ones our own capital passes before every live
deployment. That's the whole pitch: we're not selling a backtest beautifier — we're selling the
gate we use because losing our own money taught us to.
