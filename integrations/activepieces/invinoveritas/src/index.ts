import { createAction, createPiece, PieceAuth, Property } from '@activepieces/pieces-framework';
import { invinoRequest, invinoGet } from './lib/common';

function apiKey(authValue: unknown): string {
  return String(authValue || '');
}

const auth = PieceAuth.SecretText({
  displayName: 'invinoveritas API key',
  description: 'Register free at https://api.babyblueviper.com/register. Top up with Lightning (or x402/USDC) to make paid calls.',
  required: true,
});

const reason = createAction({
  name: 'reason',
  displayName: 'Premium Reasoning',
  description: 'Ask invinoveritas for paid-quality reasoning. Typical cost is about 100 sats.',
  auth,
  props: {
    question: Property.LongText({ displayName: 'Question', required: true }),
    style: Property.StaticDropdown({
      displayName: 'Style',
      required: false,
      defaultValue: 'normal',
      options: {
        options: [
          { label: 'Short', value: 'short' },
          { label: 'Normal', value: 'normal' },
          { label: 'Comprehensive', value: 'comprehensive' },
        ],
      },
    }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/reason', ctx.propsValue);
  },
});

const decision = createAction({
  name: 'decision',
  displayName: 'Structured Decision',
  description: 'Get a structured recommendation with confidence and risk notes. Typical cost is about 180 sats.',
  auth,
  props: {
    goal: Property.ShortText({ displayName: 'Goal', required: true }),
    question: Property.LongText({ displayName: 'Decision question', required: true }),
    context: Property.LongText({ displayName: 'Context', required: false }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/decision', ctx.propsValue);
  },
});

const review = createAction({
  name: 'review',
  displayName: 'Governed Review (front door)',
  description: 'Capital-scale-aware governed review of a trade, diff, command, or plan — the same gate our own live Bitcoin bot passes before every entry. Returns an approve/revise/reject verdict. ~250 sats.',
  auth,
  props: {
    artifact: Property.LongText({ displayName: 'Artifact to review', required: true }),
    artifact_type: Property.StaticDropdown({
      displayName: 'Artifact type',
      required: false,
      defaultValue: 'general',
      options: {
        options: [
          { label: 'Code diff', value: 'code_diff' },
          { label: 'Shell command', value: 'shell_command' },
          { label: 'Plan', value: 'plan' },
          { label: 'Config change', value: 'config_change' },
          { label: 'Analysis', value: 'analysis' },
          { label: 'Agent output', value: 'agent_output' },
          { label: 'General', value: 'general' },
        ],
      },
    }),
    context: Property.LongText({ displayName: 'Context', required: false }),
    severity_threshold: Property.StaticDropdown({
      displayName: 'Severity threshold',
      required: false,
      defaultValue: 'medium',
      options: {
        options: [
          { label: 'Low', value: 'low' },
          { label: 'Medium', value: 'medium' },
          { label: 'High', value: 'high' },
        ],
      },
    }),
    include_trading_state: Property.Checkbox({ displayName: 'Include live trading state (capital-scale-aware)', required: false, defaultValue: false }),
    sign: Property.Checkbox({ displayName: 'Sign verdict (portable proof to attach to your output — agent-to-agent handshake)', required: false, defaultValue: false }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/review', ctx.propsValue);
  },
});

const prove = createAction({
  name: 'prove',
  displayName: 'Prove (signed proof)',
  description: 'Signed, independently-verifiable proof of a prior execution — the attestation-after to Review\'s verdict-before. Public verify at /attestations/{proof_id}.',
  auth,
  props: {
    action_id: Property.ShortText({ displayName: 'Action ID (execution to attest)', required: true }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/prove', ctx.propsValue);
  },
});

const ledger = createAction({
  name: 'ledger',
  displayName: 'Ledger (public verdict track record)',
  description: 'The public, signed, on-chain-verifiable verdict track record — verify our record against our published key without trusting us. We publish our failures too. Free, no auth.',
  auth,
  props: {
    entry: Property.ShortText({ displayName: 'Entry number (blank = full index)', required: false }),
  },
  async run(ctx) {
    const entry = String((ctx.propsValue as { entry?: string }).entry || '');
    return invinoGet(apiKey(ctx.auth), entry ? `/ledger/${entry}` : '/ledger');
  },
});

const verifyProof = createAction({
  name: 'verify_proof',
  displayName: 'Verify Proof (agent-to-agent trust handshake)',
  description: 'Another agent handed you output with an invinoveritas proof? Verify it WITHOUT trusting that agent or us — confirms we issued the verdict (recomputes the Nostr id, checks the schnorr signature vs our published key). Pass expect_artifact_hash to bind it to the exact output you received. Free, no auth.',
  auth,
  props: {
    event: Property.Json({ displayName: 'Signed proof event (the JSON the counterparty gave you)', required: false }),
    proof_id: Property.ShortText({ displayName: 'Or a stored attestation proof_id', required: false }),
    expect_artifact_hash: Property.ShortText({ displayName: 'Expected artifact hash (sha256 of the output you received)', required: false }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/verify-proof', ctx.propsValue);
  },
});

const residenceAct = createAction({
  name: 'residence_act',
  displayName: 'Residence Act (governed bundle)',
  description: 'One governed call — your home reasons about your intent, governs it through the review gate, and remembers it. Deterministic house rules; priced below the sum of its parts. Returns a governed verdict (Rule 9: you take any irreversible action yourself).',
  auth,
  props: {
    intent: Property.LongText({ displayName: 'Intent (what your home should reason about / govern)', required: true }),
    artifact: Property.LongText({ displayName: 'Artifact to govern (optional)', required: false }),
    artifact_type: Property.StaticDropdown({
      displayName: 'Artifact type',
      required: false,
      defaultValue: 'general',
      options: {
        options: [
          { label: 'Code diff', value: 'code_diff' },
          { label: 'Shell command', value: 'shell_command' },
          { label: 'Plan', value: 'plan' },
          { label: 'Config change', value: 'config_change' },
          { label: 'Analysis', value: 'analysis' },
          { label: 'Agent output', value: 'agent_output' },
          { label: 'General', value: 'general' },
        ],
      },
    }),
    require_review: Property.Checkbox({ displayName: 'Require the governance review gate', required: false, defaultValue: true }),
    remember: Property.Checkbox({ displayName: 'Remember this act (continuity)', required: false, defaultValue: true }),
    max_spend_sats: Property.Number({ displayName: 'Max spend sats (hard deterministic cap)', required: false }),
  },
  async run(ctx) {
    const p = ctx.propsValue;
    const body: Record<string, unknown> = {
      intent: p.intent,
      artifact_type: p.artifact_type ?? 'general',
      policy: {
        require_review: p.require_review ?? true,
        remember: p.remember ?? true,
        max_spend_sats: p.max_spend_sats ?? null,
      },
    };
    if (p.artifact) body['artifact'] = p.artifact;
    return invinoRequest(apiKey(ctx.auth), '/residence/act', body);
  },
});

const regime = createAction({
  name: 'regime',
  displayName: 'Regime (macro risk-off feed)',
  description: 'Macro risk-off DATA feed (OOS-validated, facts-only) — the regime signal our own live Bitcoin bot scales risk by. Not financial advice.',
  auth,
  props: {},
  async run(ctx) {
    return invinoGet(apiKey(ctx.auth), '/regime');
  },
});

const signalsTeaser = createAction({
  name: 'signals_teaser',
  displayName: 'Signals — free BTC vol-expansion teaser',
  description: 'Free shop-window: the BTC vol-expansion regime read — the exact gate our own live Bitcoin earner enters on. Facts-only, not advice.',
  auth,
  props: {},
  async run(ctx) {
    return invinoGet(apiKey(ctx.auth), '/signals');
  },
});

const signals = createAction({
  name: 'signals',
  displayName: 'Signals — full live derivatives set (paid)',
  description: 'Live Hyperliquid derivatives signals: per-coin funding + 24h funding-delta, basis, open interest, vol-expansion regime, realized vol, BTC DVOL (multi-coin). Facts-only, not advice.',
  auth,
  props: {},
  async run(ctx) {
    return invinoGet(apiKey(ctx.auth), '/signals/full');
  },
});

const marketsAct = createAction({
  name: 'markets_act',
  displayName: 'Markets Bundle',
  description: 'One governed call: regime + live derivatives signals + ecosystem brief + an optional governance review of a proposed trade. Priced below the sum of its members. Facts-only data + a governance verdict, never P&L/advice.',
  auth,
  props: {
    artifact: Property.LongText({ displayName: 'Proposed trade/plan to review (optional)', required: false }),
    artifact_type: Property.ShortText({ displayName: 'Artifact type', required: false, defaultValue: 'general' }),
    context: Property.LongText({ displayName: 'Context (optional)', required: false }),
  },
  async run(ctx) {
    const p = ctx.propsValue;
    const body: Record<string, unknown> = { artifact_type: p.artifact_type ?? 'general' };
    if (p.artifact) body['artifact'] = p.artifact;
    if (p.context) body['context'] = p.context;
    return invinoRequest(apiKey(ctx.auth), '/markets/act', body);
  },
});

const marketplaceBuy = createAction({
  name: 'marketplace_buy',
  displayName: 'Buy Marketplace Service',
  description: 'Buy an agent marketplace listing with sats. Sellers receive 95%.',
  auth,
  props: {
    offer_id: Property.ShortText({ displayName: 'Offer ID', required: true }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/offers/buy', ctx.propsValue);
  },
});

const memoryStore = createAction({
  name: 'memory_store',
  displayName: 'Store Agent Memory',
  description: 'Persist workflow memory in invinoveritas.',
  auth,
  props: {
    agent_id: Property.ShortText({ displayName: 'Agent ID', required: true }),
    key: Property.ShortText({ displayName: 'Key', required: true }),
    value: Property.LongText({ displayName: 'Value', required: true }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/memory/store', ctx.propsValue);
  },
});

const memoryGet = createAction({
  name: 'memory_get',
  displayName: 'Get Agent Memory',
  description: 'Retrieve persisted agent memory.',
  auth,
  props: {
    agent_id: Property.ShortText({ displayName: 'Agent ID', required: true }),
    key: Property.ShortText({ displayName: 'Key', required: true }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/memory/get', ctx.propsValue);
  },
});

const memoryList = createAction({
  name: 'memory_list',
  displayName: 'List Agent Memory Keys',
  description: 'List all memory keys stored for this agent. Free.',
  auth,
  props: {
    agent_id: Property.ShortText({ displayName: 'Agent ID', required: true }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/memory/list', ctx.propsValue);
  },
});

const memoryDelete = createAction({
  name: 'memory_delete',
  displayName: 'Delete Agent Memory',
  description: 'Permanently delete a stored memory entry by key. Free.',
  auth,
  props: {
    agent_id: Property.ShortText({ displayName: 'Agent ID', required: true }),
    key: Property.ShortText({ displayName: 'Key', required: true }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/memory/delete', ctx.propsValue);
  },
});

const a2aDelegate = createAction({
  name: 'a2a_delegate',
  displayName: 'A2A Delegate',
  description: 'Discover, quote, or delegate tasks to invinoveritas over A2A.',
  auth,
  props: {
    operation: Property.StaticDropdown({
      displayName: 'Operation',
      required: true,
      defaultValue: 'task_delegation',
      options: {
        options: [
          { label: 'Discover', value: 'discover' },
          { label: 'Quote', value: 'quote' },
          { label: 'Task Delegation', value: 'task_delegation' },
        ],
      },
    }),
    task: Property.Json({ displayName: 'Task JSON', required: false }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/a2a', {
      operation: ctx.propsValue.operation,
      task: ctx.propsValue.task ?? {},
    });
  },
});

const growthAttackPlan = createAction({
  name: 'growth_attack_plan',
  displayName: 'Growth + PNL Attack Plan',
  description: 'Generate a default-aggressive, risk-bounded plan for registrations, paid usage, marketplace volume, Premium Spawn Kit conversion, and daily sats PNL.',
  auth,
  props: {
    objective: Property.LongText({ displayName: 'Objective', required: true }),
    context: Property.LongText({ displayName: 'Context', required: false }),
    budget_sats: Property.Number({ displayName: 'Budget Sats', required: false }),
  },
  async run(ctx) {
    const prompt = [
      'Default posture: aggressive growth and PNL capture, bounded by Bitcoin/Lightning-only payments, budget limits, and explicit risk controls.',
      'Produce concrete next actions that drive registrations, funded accounts, paid reasoning, marketplace purchases, Premium Spawn Kit conversion, referrals, seller withdrawals, or Sovereign Earner support.',
      `Objective: ${ctx.propsValue.objective}`,
      `Context: ${ctx.propsValue.context ?? ''}`,
      `Budget sats: ${ctx.propsValue.budget_sats ?? 'not specified'}`,
    ].join('\n');
    return invinoRequest(apiKey(ctx.auth), '/decision', {
      goal: 'Maximize invinoveritas growth and daily sats PNL with default-aggressive execution.',
      question: prompt,
      context: ctx.propsValue.context ?? '',
    });
  },
});

const sovereignExecute = createAction({
  name: 'sovereign_execute',
  displayName: 'Sovereign Earner Execute',
  description: 'Pay sats upfront to queue an aggressive, risk-bounded Sovereign Earner directive. Platform keeps 40%; 60% becomes strategy budget.',
  auth,
  props: {
    fee_sats: Property.Number({ displayName: 'Fee Sats', required: true, defaultValue: 1000 }),
    direction: Property.StaticDropdown({
      displayName: 'Direction',
      required: false,
      defaultValue: 'auto',
      options: {
        options: [
          { label: 'Auto', value: 'auto' },
          { label: 'Long', value: 'long' },
          { label: 'Short', value: 'short' },
        ],
      },
    }),
    leverage: Property.Number({ displayName: 'Leverage', required: false, defaultValue: 3 }),
    duration_hours: Property.Number({ displayName: 'Duration Hours', required: false, defaultValue: 2 }),
    stop_loss_pct: Property.Number({ displayName: 'Stop Loss %', required: false, defaultValue: 0.35 }),
    take_profit_pct: Property.Number({ displayName: 'Take Profit %', required: false, defaultValue: 0.7 }),
    thesis: Property.LongText({ displayName: 'Thesis', required: false }),
  },
  async run(ctx) {
    return invinoRequest(apiKey(ctx.auth), '/sovereign/execute', {
      ...ctx.propsValue,
      agent_id: 'activepieces',
    });
  },
});

export const invinoveritas = createPiece({
  displayName: 'invinoveritas',
  auth,
  minimumSupportedRelease: '0.28.0',
  logoUrl: 'https://api.babyblueviper.com/favicon.ico',
  authors: ['babyblueviper1'],
  actions: [reason, decision, review, prove, ledger, verifyProof, residenceAct, regime, signalsTeaser, signals, marketsAct, marketplaceBuy, memoryStore, memoryGet, memoryList, memoryDelete, a2aDelegate, growthAttackPlan, sovereignExecute],
  triggers: [],
});
