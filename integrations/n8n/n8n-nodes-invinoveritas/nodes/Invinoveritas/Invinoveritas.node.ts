type Operation = 'reason' | 'decision' | 'memoryStore' | 'memoryGet' | 'memoryList' | 'memoryDelete' | 'marketplaceBuy' | 'a2aDelegate' | 'growthAttackPlan' | 'sovereignExecute' | 'review' | 'prove' | 'ledger' | 'verifyProof' | 'residenceAct' | 'regime' | 'signalsTeaser' | 'signals' | 'marketsAct';

const GET_OPS: Operation[] = ['regime', 'signalsTeaser', 'signals', 'ledger'];

const BASE_URL = 'https://api.babyblueviper.com';

export class Invinoveritas {
  description = {
    displayName: 'invinoveritas',
    name: 'invinoveritas',
    icon: 'file:invinoveritas.svg',
    group: ['transform'],
    version: 2,
    subtitle: '={{$parameter["operation"]}}',
    description: 'The verification layer for autonomous agents — /review (verdict before an irreversible action), /prove (signed proof after), /ledger (public verdict track record). Plus reasoning, decisions, memory, marketplace + A2A as supporting tools. Bitcoin/Lightning + x402.',
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
          { name: 'Memory List', value: 'memoryList' },
          { name: 'Memory Delete', value: 'memoryDelete' },
          { name: 'A2A Delegate', value: 'a2aDelegate' },
          { name: 'Review (capital-scale-aware governed verdict — front door)', value: 'review' },
          { name: 'Prove (signed, independently-verifiable proof of a prior execution)', value: 'prove' },
          { name: 'Ledger (public signed verdict track record — verify without trusting us; free)', value: 'ledger' },
          { name: 'Verify Proof (check a counterparty\'s proof — agent-to-agent trust handshake; free)', value: 'verifyProof' },
          { name: 'Residence Act (optional one-call governed bundle)', value: 'residenceAct' },
          { name: 'Regime (macro risk-off feed)', value: 'regime' },
          { name: 'Signals — free BTC vol-expansion teaser', value: 'signalsTeaser' },
          { name: 'Signals — full live derivatives set (paid)', value: 'signals' },
          { name: 'Markets Bundle (regime + signals + brief + optional review)', value: 'marketsAct' },
        ],
      },
      { displayName: 'Question / Objective / Intent', name: 'question', type: 'string', default: '' },
      { displayName: 'Artifact (trade/diff/command/plan to review or govern)', name: 'artifact', type: 'string', default: '' },
      { displayName: 'Artifact Type', name: 'artifactType', type: 'string', default: 'general' },
      { displayName: 'Context', name: 'context', type: 'string', default: '' },
      { displayName: 'Action ID (for Prove — execution to attest)', name: 'actionId', type: 'string', default: '' },
      { displayName: 'Ledger Entry (for Ledger — entry number, blank = full index)', name: 'ledgerEntry', type: 'string', default: '' },
      { displayName: 'Proof Event JSON (for Verify Proof — the signed event a counterparty gave you)', name: 'proofEvent', type: 'string', typeOptions: { rows: 4 }, default: '' },
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
        artifact: this.getNodeParameter('artifact', i, '') as string,
        artifactType: this.getNodeParameter('artifactType', i, 'general') as string,
        context: this.getNodeParameter('context', i, '') as string,
        actionId: this.getNodeParameter('actionId', i, '') as string,
        ledgerEntry: this.getNodeParameter('ledgerEntry', i, '') as string,
        proofEvent: this.getNodeParameter('proofEvent', i, '') as string,
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
      const isGet = GET_OPS.includes(operation);
      const ledgerEntry = this.getNodeParameter('ledgerEntry', i, '') as string;
      const path = operation === 'ledger' && ledgerEntry ? `/ledger/${ledgerEntry}` : pathFor(operation);
      const response = await this.helpers.httpRequest({
        method: isGet ? 'GET' : 'POST',
        url: `${BASE_URL}${path}`,
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
          'User-Agent': 'n8n-nodes-invinoveritas/0.4.0',
          'X-Invino-Integration': 'n8n',
        },
        ...(isGet ? {} : { body }),
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
  if (operation === 'memoryList') return '/memory/list';
  if (operation === 'memoryDelete') return '/memory/delete';
  if (operation === 'review') return '/review';
  if (operation === 'prove') return '/prove';
  if (operation === 'ledger') return '/ledger';
  if (operation === 'verifyProof') return '/verify-proof';
  if (operation === 'residenceAct') return '/residence/act';
  if (operation === 'regime') return '/regime';
  if (operation === 'signalsTeaser') return '/signals';
  if (operation === 'signals') return '/signals/full';
  if (operation === 'marketsAct') return '/markets/act';
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
  if (operation === 'memoryList') return { agent_id: p.agentId };
  if (operation === 'memoryDelete') return { agent_id: p.agentId, key: p.memoryKey };
  if (operation === 'a2aDelegate') return { operation: p.a2aOperation, task: { goal: p.question, context: p.context } };
  if (operation === 'review') return {
    artifact: p.artifact || p.question,
    artifact_type: p.artifactType || 'general',
    context: p.context,
    severity_threshold: 'medium',
    include_trading_state: false,
    sign: true,   // n8n flows passing review output downstream want the portable proof attached
  };
  if (operation === 'prove') return { action_id: p.actionId };
  if (operation === 'verifyProof') {
    let ev: any = undefined;
    try { ev = p.proofEvent ? JSON.parse(p.proofEvent) : undefined; } catch (e) { ev = undefined; }
    return { event: ev };
  }
  if (operation === 'residenceAct') {
    const body: Record<string, any> = {
      intent: p.question,
      artifact_type: p.artifactType || 'general',
      policy: { require_review: true, remember: true, max_spend_sats: null },
    };
    if (p.artifact) body.artifact = p.artifact;
    return body;
  }
  if (operation === 'marketsAct') {
    const body: Record<string, any> = { artifact_type: p.artifactType || 'general' };
    if (p.artifact) body.artifact = p.artifact;
    if (p.context) body.context = p.context;
    return body;
  }
  return {
    goal: 'Maximize invinoveritas growth and daily sats PNL with default-aggressive execution.',
    question: `Default posture: aggressive growth and PNL capture, bounded by Bitcoin/Lightning-only payments, budget limits, and explicit risk controls.\nObjective: ${p.question}\nContext: ${p.context}\nBudget sats: ${p.budgetSats}`,
    context: p.context,
  };
}
