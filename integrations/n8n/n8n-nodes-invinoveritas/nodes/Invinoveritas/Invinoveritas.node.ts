type Operation = 'reason' | 'decision' | 'memoryStore' | 'memoryGet' | 'marketplaceBuy' | 'a2aDelegate' | 'growthAttackPlan' | 'sovereignExecute';

const BASE_URL = 'https://api.babyblueviper.com';

export class Invinoveritas {
  description = {
    displayName: 'invinoveritas',
    name: 'invinoveritas',
    icon: 'file:invinoveritas.svg',
    group: ['transform'],
    version: 2,
    subtitle: '={{$parameter["operation"]}}',
    description: 'Default-aggressive Bitcoin/Lightning-native reasoning, decisions, memory, marketplace, A2A, and growth/PNL attack planning.',
    defaults: { name: 'invinoveritas' },
    inputs: ['main'],
    outputs: ['main'],
    credentials: [{ name: 'invinoveritasApi', required: true }],
    properties: [
      {
        displayName: 'Operation',
        name: 'operation',
        type: 'options',
        default: 'growthAttackPlan',
        options: [
          { name: 'Growth + PNL Attack Plan', value: 'growthAttackPlan' },
          { name: 'Premium Reasoning', value: 'reason' },
          { name: 'Structured Decision', value: 'decision' },
          { name: 'Marketplace Buy', value: 'marketplaceBuy' },
          { name: 'Sovereign Earner Execute', value: 'sovereignExecute' },
          { name: 'Memory Store', value: 'memoryStore' },
          { name: 'Memory Get', value: 'memoryGet' },
          { name: 'A2A Delegate', value: 'a2aDelegate' },
        ],
      },
      { displayName: 'Question / Objective', name: 'question', type: 'string', default: '', required: true },
      { displayName: 'Context', name: 'context', type: 'string', default: '' },
      { displayName: 'Offer ID', name: 'offerId', type: 'string', default: '' },
      { displayName: 'Agent ID', name: 'agentId', type: 'string', default: '' },
      { displayName: 'Memory Key', name: 'memoryKey', type: 'string', default: '' },
      { displayName: 'Memory Value', name: 'memoryValue', type: 'string', default: '' },
      { displayName: 'A2A Operation', name: 'a2aOperation', type: 'string', default: 'task_delegation' },
      { displayName: 'Budget Sats', name: 'budgetSats', type: 'number', default: 5000 },
      { displayName: 'Direction', name: 'direction', type: 'options', default: 'auto', options: [
        { name: 'Auto', value: 'auto' },
        { name: 'Long', value: 'long' },
        { name: 'Short', value: 'short' },
      ] },
      { displayName: 'Leverage', name: 'leverage', type: 'number', default: 3 },
      { displayName: 'Duration Hours', name: 'durationHours', type: 'number', default: 2 },
      { displayName: 'Stop Loss %', name: 'stopLossPct', type: 'number', default: 0.35 },
      { displayName: 'Take Profit %', name: 'takeProfitPct', type: 'number', default: 0.7 },
    ],
  };

  async execute(this: any) {
    const items = this.getInputData();
    const credentials = await this.getCredentials('invinoveritasApi');
    const apiKey = credentials.apiKey as string;
    const results = [];
    for (let i = 0; i < items.length; i++) {
      const operation = this.getNodeParameter('operation', i) as Operation;
      const body = buildBody(operation, {
        question: this.getNodeParameter('question', i, '') as string,
        context: this.getNodeParameter('context', i, '') as string,
        offerId: this.getNodeParameter('offerId', i, '') as string,
        agentId: this.getNodeParameter('agentId', i, '') as string,
        memoryKey: this.getNodeParameter('memoryKey', i, '') as string,
        memoryValue: this.getNodeParameter('memoryValue', i, '') as string,
        a2aOperation: this.getNodeParameter('a2aOperation', i, 'task_delegation') as string,
        budgetSats: this.getNodeParameter('budgetSats', i, 5000) as number,
        direction: this.getNodeParameter('direction', i, 'auto') as string,
        leverage: this.getNodeParameter('leverage', i, 3) as number,
        durationHours: this.getNodeParameter('durationHours', i, 2) as number,
        stopLossPct: this.getNodeParameter('stopLossPct', i, 0.35) as number,
        takeProfitPct: this.getNodeParameter('takeProfitPct', i, 0.7) as number,
      });
      const response = await this.helpers.httpRequest({
        method: 'POST',
        url: `${BASE_URL}${pathFor(operation)}`,
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
          'User-Agent': 'n8n-nodes-invinoveritas/0.2.0',
          'X-Invino-Integration': 'n8n',
        },
        body,
        json: true,
      });
      results.push({ json: response });
    }
    return [results];
  }
}

function pathFor(operation: Operation): string {
  if (operation === 'reason') return '/reason';
  if (operation === 'decision' || operation === 'growthAttackPlan') return '/decision';
  if (operation === 'marketplaceBuy') return '/offers/buy';
  if (operation === 'sovereignExecute') return '/sovereign/execute';
  if (operation === 'memoryStore') return '/memory/store';
  if (operation === 'memoryGet') return '/memory/get';
  return '/a2a';
}

function buildBody(operation: Operation, p: Record<string, any>) {
  if (operation === 'reason') return { question: p.question, style: 'normal' };
  if (operation === 'decision') return { goal: 'Make a structured decision', question: p.question, context: p.context };
  if (operation === 'marketplaceBuy') return { offer_id: p.offerId };
  if (operation === 'sovereignExecute') return {
    fee_sats: p.budgetSats,
    direction: p.direction,
    leverage: p.leverage,
    duration_hours: p.durationHours,
    stop_loss_pct: p.stopLossPct,
    take_profit_pct: p.takeProfitPct,
    thesis: p.question,
    agent_id: p.agentId || 'n8n',
  };
  if (operation === 'memoryStore') return { agent_id: p.agentId, key: p.memoryKey, value: p.memoryValue };
  if (operation === 'memoryGet') return { agent_id: p.agentId, key: p.memoryKey };
  if (operation === 'a2aDelegate') return { operation: p.a2aOperation, task: { goal: p.question, context: p.context } };
  return {
    goal: 'Maximize invinoveritas growth and daily sats PNL with default-aggressive execution.',
    question: `Objective: ${p.question}\nContext: ${p.context}\nBudget sats: ${p.budgetSats}`,
    context: p.context,
  };
}
