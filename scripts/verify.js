/* The engine must reproduce every answer harvested from I-MAGIC.  usage: node scripts/verify.js */
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const H = path.join(ROOT, 'data', 'imagic-harvest');
const rules = JSON.parse(fs.readFileSync(path.join(ROOT, 'rules.json'), 'utf8'));
const { resolve } = require(path.join(ROOT, 'engine.js'));
const codes = rows => rows.map(r => r.code + r.ext).sort().join('|');
const EPI = { 'initial encounter': 'A', 'subsequent encounter': 'D', 'sequela': 'S' };
let n = 0; const bad = [];
if (!fs.existsSync(H)) { console.log('no data/imagic-harvest; run scripts/harvest.py first'); process.exit(2); }
for (const f of fs.readdirSync(H).filter(x => x.endsWith('.json') && !x.startsWith('_'))) {
  const rec = JSON.parse(fs.readFileSync(path.join(H, f), 'utf8'));
  const id = rec.sct;
  const check = (label, answers, expect) => { n++; const r = resolve(rules, id, answers); const got = codes(r.rows || []); if (got !== codes(expect)) bad.push(`${id} ${label}: engine=${got} imagic=${codes(expect)}`); };
  check('base', {}, rec.base.rows);
  for (const v of rec.variants) {
    if (v.kind === 'sex') check(`sex=${v.label}`, { sex: v.label }, v.result.rows);
    else if (v.kind === 'age') check(`age=${v.age_days}d`, { age_days: v.age_days }, v.result.rows);
    else if (v.kind === 'laterality') check(`lat=${v.value}`, { refine: 'none', laterality: v.value, episode: 'A' }, v.result.rows);
    else if (v.kind === 'episode') check(`epi=${v.value}`, { refine: 'none', episode: EPI[v.value] }, v.result.rows);
    else if (v.kind === 'refine') check(`refine=${v.value}`, { refine: v.value }, v.result.rows);
  }
}
console.log(`${n} conditions compared, ${bad.length} mismatches`); bad.forEach(b => console.log('  ' + b));
process.exit(bad.length ? 1 : 0);
