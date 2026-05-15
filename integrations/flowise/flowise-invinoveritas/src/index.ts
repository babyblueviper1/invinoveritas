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
      'User-Agent': 'flowise-invinoveritas/0.2.0',
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
      '',
      'Produce concrete next actions that drive registrations, funded accounts, paid reasoning, marketplace purchases, Premium Spawn Kit conversion, referrals, seller withdrawals, or Sovereign Earner support.',
      `Objective: ${objective}`,
      `Context: ${context}`,
      `Budget sats: ${budgetSats ?? 'not specified'}`,
    ].join('\n'),
    context,
  );
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
];
