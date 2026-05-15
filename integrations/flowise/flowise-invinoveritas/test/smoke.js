const fs = require('fs');
const path = require('path');

for (const file of ['package.json', 'src/index.ts']) {
  const full = path.join(__dirname, '..', file);
  if (!fs.existsSync(full)) throw new Error(`missing ${file}`);
}

const source = fs.readFileSync(path.join(__dirname, '..', 'src/index.ts'), 'utf8');
for (const token of ['invinoReason', 'invinoDecision', 'invinoGrowthAttackPlan', 'invinoSovereignExecute', 'X-Invino-Integration']) {
  if (!source.includes(token)) throw new Error(`missing ${token}`);
}

console.log('flowise smoke ok');
