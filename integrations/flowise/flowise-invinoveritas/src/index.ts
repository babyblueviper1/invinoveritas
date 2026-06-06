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
      'User-Agent': 'flowise-invinoveritas/0.4.0',
      'X-Invino-Integration': config.integration || 'flowise',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`invinoveritas ${path} failed: ${response.status} ${await response.text()}`);
  }
  return response.json();
}

async function get(config: InvinoConfig, path: string, x402 = false) {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${config.apiKey}`,
    'User-Agent': 'flowise-invinoveritas/0.5.0',
    'X-Invino-Integration': config.integration || 'flowise',
  };
  if (x402) headers['X-Payment-Scheme'] = 'x402';
  const response = await fetch(`${BASE_URL}${path}`, { method: 'GET', headers });
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

export async function invinoReview(
  config: InvinoConfig,
  artifact: string,
  artifactType = 'general',
  context = '',
  severityThreshold: 'low' | 'medium' | 'high' = 'medium',
  includeTradingState = false,
) {
  return post(config, '/review', {
    artifact,
    artifact_type: artifactType,
    context,
    severity_threshold: severityThreshold,
    include_trading_state: includeTradingState,
  });
}

export async function invinoProve(config: InvinoConfig, actionId: string) {
  // Signed, independently-verifiable proof of a prior execution (the verdict-after to review's verdict-before).
  return post(config, '/prove', { action_id: actionId });
}

export async function invinoLedger(config: InvinoConfig, entry = '') {
  // The public, signed, on-chain-verifiable verdict track record — verify without trusting us. Free, no auth.
  return get(config, entry ? `/ledger/${entry}` : '/ledger');
}

export async function invinoResidenceAct(
  config: InvinoConfig,
  intent: string,
  artifact = '',
  artifactType = 'general',
  requireReview = true,
  remember = true,
  maxSpendSats?: number,
) {
  const body: Record<string, unknown> = {
    intent,
    artifact_type: artifactType,
    policy: {
      require_review: requireReview,
      remember,
      max_spend_sats: maxSpendSats ?? null,
    },
  };
  if (artifact) body.artifact = artifact;
  return post(config, '/residence/act', body);
}

// ---- Markets / trading intelligence (facts-only, never P&L/advice) ----

export async function invinoRegime(config: InvinoConfig, x402 = false) {
  return get(config, '/regime', x402);
}

export async function invinoSignalsTeaser(config: InvinoConfig) {
  // Free shop-window: BTC vol-expansion regime read (the gate our live earner enters on).
  return get(config, '/signals');
}

export async function invinoSignals(config: InvinoConfig, x402 = false) {
  // Paid full multi-coin live Hyperliquid derivatives set.
  return get(config, '/signals/full', x402);
}

export async function invinoMarketsAct(
  config: InvinoConfig,
  artifact = '',
  artifactType = 'general',
  context = '',
  coins?: string[],
  maxSpendSats?: number,
) {
  // The Markets Bundle: regime + live signals + brief + optional governance review.
  const body: Record<string, unknown> = { artifact_type: artifactType };
  if (coins && coins.length) body.coins = coins;
  if (artifact) body.artifact = artifact;
  if (context) body.context = context;
  if (maxSpendSats !== undefined) body.max_spend_sats = maxSpendSats;
  return post(config, '/markets/act', body);
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
    label: 'invinoveritas Review (front door)',
    name: 'invinoveritasReview',
    description: 'Capital-scale-aware governed review of a trade, diff, command, or plan — the same gate our live Bitcoin bot passes before every entry. ~250 sats.',
  },
  {
    label: 'invinoveritas Prove (signed proof)',
    name: 'invinoveritasProve',
    description: 'Signed, independently-verifiable proof of a prior execution — the attestation-after to Review\'s verdict-before. Public verify at /attestations/{proof_id}.',
  },
  {
    label: 'invinoveritas Ledger (public track record)',
    name: 'invinoveritasLedger',
    description: 'The public, signed, on-chain-verifiable verdict track record — verify our record against our published key without trusting us. We publish our failures too. Free.',
  },
  {
    label: 'invinoveritas Residence Act (optional governed bundle)',
    name: 'invinoveritasResidenceAct',
    description: 'Optional one governed call — reasons + governs + remembers your intent. Deterministic house rules; priced below the sum of its parts.',
  },
  {
    label: 'invinoveritas Regime (risk-off feed)',
    name: 'invinoveritasRegime',
    description: 'Macro risk-off DATA feed (OOS-validated, facts-only) — the regime signal our own bot scales risk by.',
  },
  {
    label: 'invinoveritas Signals (live derivatives)',
    name: 'invinoveritasSignals',
    description: 'Live Hyperliquid derivatives signals — funding + 24h delta, basis, open interest, the vol-expansion regime our bot enters on, realized vol, BTC DVOL. Free BTC teaser + paid multi-coin set. Facts-only, never advice.',
  },
  {
    label: 'invinoveritas Markets Bundle',
    name: 'invinoveritasMarketsAct',
    description: 'One governed call: regime + live signals + ecosystem brief + optional governance review of a proposed trade. Priced below the sum of its members.',
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
