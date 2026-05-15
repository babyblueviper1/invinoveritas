import { createAction, createPiece, PieceAuth, Property } from '@activepieces/pieces-framework';
import { invinoRequest } from './lib/common';

function apiKey(authValue: unknown): string {
  return String(authValue || '');
}

const auth = PieceAuth.SecretText({
  displayName: 'invinoveritas API key',
  description: 'Register free at https://api.babyblueviper.com/register. Top up with Lightning when starter sats run out.',
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
      '',
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
  actions: [reason, decision, marketplaceBuy, memoryStore, memoryGet, a2aDelegate, growthAttackPlan, sovereignExecute],
  triggers: [],
});
