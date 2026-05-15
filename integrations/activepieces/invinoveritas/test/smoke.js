const fs = require('fs');
const path = require('path');

for (const file of ['package.json', 'src/index.ts', 'src/lib/common.ts']) {
  const full = path.join(__dirname, '..', file);
  if (!fs.existsSync(full)) throw new Error(`missing ${file}`);
}

const source = fs.readFileSync(path.join(__dirname, '..', 'src/index.ts'), 'utf8');
for (const token of ['growth_attack_plan', 'marketplace_buy', 'a2a_delegate', 'sovereign_execute']) {
  if (!source.includes(token)) throw new Error(`missing ${token}`);
}

const common = fs.readFileSync(path.join(__dirname, '..', 'src/lib/common.ts'), 'utf8');
if (!common.includes('X-Invino-Integration')) throw new Error('missing attribution header');

console.log('activepieces smoke ok');
