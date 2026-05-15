const fs = require('fs');
const path = require('path');

for (const file of [
  'package.json',
  'nodes/Invinoveritas/Invinoveritas.node.ts',
  'credentials/InvinoveritasApi.credentials.ts',
]) {
  const full = path.join(__dirname, '..', file);
  if (!fs.existsSync(full)) throw new Error(`missing ${file}`);
}

const pkg = require('../package.json');
if (!pkg.n8n || !pkg.n8n.nodes || !pkg.n8n.credentials) {
  throw new Error('missing n8n package metadata');
}

const source = fs.readFileSync(path.join(__dirname, '..', 'nodes/Invinoveritas/Invinoveritas.node.ts'), 'utf8');
for (const token of ['growthAttackPlan', 'marketplaceBuy', 'sovereignExecute', '/sovereign/execute']) {
  if (!source.includes(token)) throw new Error(`missing ${token}`);
}

console.log('n8n smoke ok');
