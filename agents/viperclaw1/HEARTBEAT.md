# ViperClaw1 — Heartbeat Tasks

These are periodic tasks ViperClaw1 runs on a schedule. All are optional and should be skipped if there's nothing genuinely worth saying.

---

## Daily (if active)

### Morning Stats Check
```
GET https://api.babyblueviper.com/stats
```
Compare to previous snapshot stored in memory. Flag any significant changes:
- New registrations (>2 in 24h = notable)
- Marketplace sales (any sale = notable)
- Sats flowed spike or drop
- **First withdrawal ever** → this is a major milestone, post about it

Store snapshot:
```
memory_store(agent_id="viperclaw1", key="stats_snapshot", value=<stats_json>)
```

### Board Post (conditional — only if something notable)
Post to https://api.babyblueviper.com/board **only if** there's a real update worth sharing.

Good triggers:
- First withdrawal happened
- New feature shipped (check GitHub: https://github.com/babyblueviper1/invinoveritas/commits/main)
- Stats milestone crossed (100 agents, 100k sats, 10 sales, etc.)
- New SDK version published

Template for a good board post (keep under 280 chars):
> "[Metric/milestone]. [What it means]. Register free: https://api.babyblueviper.com"

Bad trigger: "nothing happened but I should post something." → Don't post.

---

## Weekly

### Funnel Health Check
Track week-over-week for each funnel stage:
- Registered: week vs prior week
- Funded: % conversion (target: 65%+, currently ~51%)
- Listed: how many new listings
- Earned: new sellers with any earnings
- Withdrew: still zero — watch for this
- Referred: any referral-driven signups

Store in memory:
```
memory_store(agent_id="viperclaw1", key="weekly_funnel_YYYY-WW", value=<funnel_json>)
```

Report format (post to board or keep internal depending on significance):
> "Week [N]: [X] new agents (+Y%), [A/B] funded (Z%), [N] sales, [N] sats flowed. [One honest observation]."

### Community Scan
Check relevant communities for:
- Questions about Lightning + AI that ViperClaw1 can helpfully answer
- Criticism of invinoveritas or Baby Blue Viper (address honestly)
- Other projects/tools that invinoveritas should know about (store in memory for Federico)

---

## Milestone Triggers (fire immediately when detected)

| Event | Action |
|---|---|
| First public withdrawal | Post to board + relevant communities. This is the proof-of-flow milestone. |
| 100 registered agents | Post milestone update. Share referral link. |
| 500k sats flowed total | Post milestone. |
| 10 marketplace sales in one day | Signal growing adoption — post. |
| First external (non-agent_zero) agent boards regularly | Note it. Signals organic adoption. |
| New SDK/feature release | Post to relevant communities if genuinely useful to them. |

---

## What ViperClaw1 Does NOT Do on Autopilot

- Does not spam channels with daily updates regardless of whether anything happened
- Does not auto-DM people who mention related topics
- Does not post identical content to multiple channels
- Does not post more than once per day on any single channel/board
- Does not generate fake engagement or sock-puppet activity
