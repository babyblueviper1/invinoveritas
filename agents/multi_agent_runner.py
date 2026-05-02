#!/usr/bin/env python3
"""
multi_agent_runner.py — Start all agent variants with one command.

Runs agent_trading, agent_growth, agent_research, and agent_content
as concurrent asyncio tasks. Each manages its own state, API key,
and Nostr identity.

Usage:
  python agents/multi_agent_runner.py

  # Run a subset:
  AGENTS=trading,growth python agents/multi_agent_runner.py

  # With ref code for growth agent posts:
  INVINO_REF_CODE=9UJLQG python agents/multi_agent_runner.py

Environment variables (all optional — agents self-register if not set):
  INVINO_REF_CODE          — ref code to embed in growth agent posts
  AGENT_TRADING_NSEC       — resume trading agent identity
  AGENT_TRADING_KEY        — resume trading agent API key
  AGENT_GROWTH_NSEC        — resume growth agent identity
  AGENT_GROWTH_KEY         — resume growth agent API key
  AGENT_RESEARCH_NSEC      — resume research agent identity
  AGENT_RESEARCH_KEY       — resume research agent API key
  AGENT_CONTENT_NSEC       — resume content agent identity
  AGENT_CONTENT_KEY        — resume content agent API key
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.agent_trading  as trading
import agents.agent_growth   as growth
import agents.agent_research as research
import agents.agent_content  as content

ALL_AGENTS = {
    "trading":  trading.run,
    "growth":   growth.run,
    "research": research.run,
    "content":  content.run,
}


async def supervised(name: str, fn):
    """Run an agent loop, restarting on crash with backoff."""
    backoff = 30
    while True:
        try:
            print(f"[runner] starting {name}")
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[runner] {name} crashed: {e} — restarting in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 600)
        else:
            print(f"[runner] {name} exited cleanly — restarting in 10s")
            await asyncio.sleep(10)


async def main():
    requested = os.getenv("AGENTS", "")
    if requested:
        names = [n.strip() for n in requested.split(",") if n.strip() in ALL_AGENTS]
    else:
        names = list(ALL_AGENTS.keys())

    print(f"[runner] launching agents: {', '.join(names)}")
    print(f"[runner] ref code: {os.getenv('INVINO_REF_CODE') or '(none set)'}")
    print(f"[runner] started at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n")

    tasks = [asyncio.create_task(supervised(n, ALL_AGENTS[n])) for n in names]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[runner] stopped.")
