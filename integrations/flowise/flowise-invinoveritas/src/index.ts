const BASE_URL = 'https://api.babyblueviper.com';

type InvinoConfig = {
  apiKey: string;
  integration?: string;
};

async function post(config: InvinoConfig, path: string, body: unknown) {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${config.apiKey}`,
      'Content-Type': 'application/json',
      'User-Agent': 'flowise-invinoveritas/0.3.0',
      'X-Invino-Integration': config.integration || 'flowise',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`invinoveritas ${path} failed: ${response.status} ${await response.text()}`);
  }
  return response.json();
}

export async function invinoReason(config: InvinoConfig, question: string, style = 'normal') {
  return post(config, '/reason', { question, style });
}

export async function invinoDecision(config: InvinoConfig, goal: string, question: string, context = '') {
  return post(config, '/decision', { goal, question, context });
}

export async function invinoGrowthAttackPlan(config: InvinoConfig, objective: string, context = '', budgetSats?: number) {
  return invinoDecision(
    config,
    'Maximize invinoveritas growth and daily sats PNL with default-aggressive execution.',
    [
      'Default posture: aggressive growth and PNL capture, bounded by Bitcoin/Lightning-only payments, budget limits, and explicit risk controls.',
      'Produce concrete next actions that drive registrations, funded accounts, paid reasoning, marketplace purchases, Premium Spawn Kit conversion, referrals, seller withdrawals, or Sovereign Earner support.',
      `Objective: ${objective}`,
      `Context: ${context}`,
      `Budget sats: ${budgetSats ?? 'not specified'}`,
    ].join('\n'),
    context,
  );
}

export async function invinoMemoryStore(config: InvinoConfig, agentId: string, key: string, value: string) {
  return post(config, '/memory/store', { agent_id: agentId, key, value });
}

export async function invinoMemoryGet(config: InvinoConfig, agentId: string, key: string) {
  return post(config, '/memory/get', { agent_id: agentId, key });
}

export async function invinoMemoryList(config: InvinoConfig, agentId: string) {
  return post(config, '/memory/list', { agent_id: agentId });
}

export async function invinoMemoryDelete(config: InvinoConfig, agentId: string, key: string) {
  return post(config, '/memory/delete', { agent_id: agentId, key });
}

export async function invinoSovereignExecute(
  config: InvinoConfig,
  thesis: string,
  feeSats = 1000,
  direction: 'auto' | 'long' | 'short' = 'auto',
  leverage = 3,
  durationHours = 2,
  stopLossPct = 0.35,
  takeProfitPct = 0.7,
) {
  return post(config, '/sovereign/execute', {
    fee_sats: feeSats,
    direction,
    leverage,
    duration_hours: durationHours,
    stop_loss_pct: stopLossPct,
    take_profit_pct: takeProfitPct,
    thesis,
    agent_id: 'flowise',
  });
}

export const nodes = [
  {
    label: 'invinoveritas Reason',
    name: 'invinoveritasReason',
    description: 'Paid reasoning over Bitcoin Lightning.',
  },
  {
    label: 'invinoveritas Decision',
    name: 'invinoveritasDecision',
    description: 'Structured decisions with confidence and risk notes.',
  },
  {
    label: 'invinoveritas Growth + PNL Attack Plan',
    name: 'invinoveritasGrowthAttackPlan',
    description: 'Default-aggressive growth and revenue planning for agent workflows.',
  },
  {
    label: 'invinoveritas Sovereign Earner Execute',
    name: 'invinoveritasSovereignExecute',
    description: 'Pay sats to queue an aggressive, risk-bounded Sovereign Earner directive.',
  },
  {
    label: 'invinoveritas Memory Store',
    name: 'invinoveritasMemoryStore',
    description: 'Persist key/value agent context across sessions. ~2 sats/KB (min 50), 200 KB max per entry.',
  },
  {
    label: 'invinoveritas Memory Get',
    name: 'invinoveritasMemoryGet',
    description: 'Retrieve a stored memory entry by key. ~1 sat/KB (min 20).',
  },
  {
    label: 'invinoveritas Memory List',
    name: 'invinoveritasMemoryList',
    description: 'List all memory keys stored for this agent. Free.',
  },
  {
    label: 'invinoveritas Memory Delete',
    name: 'invinoveritasMemoryDelete',
    description: 'Delete a stored memory entry by key. Free.',
  },
];
