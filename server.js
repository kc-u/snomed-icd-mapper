#!/usr/bin/env node
/* snomed-icd-mapper: local web service. People use the page, agents use the JSON API.
 *   node server.js            -> http://localhost:8765
 * env: PORT (8765), PYTHON (python; needs `requests` for live I-MAGIC queries), NO_LIVE=1 to disable live mode.
 */
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');
const { URL } = require('url');

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 8765);
const PYTHON = process.env.PYTHON || 'python';
const LIVE = !process.env.NO_LIVE;
const rules = JSON.parse(fs.readFileSync(path.join(ROOT, 'rules.json'), 'utf8'));
const tw = JSON.parse(fs.readFileSync(path.join(ROOT, 'tw2023.json'), 'utf8'));
const { resolve } = require(path.join(ROOT, 'engine.js'));
const liveCache = new Map();
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png' };

/* ---------- Taiwan 2023 edition check ---------- */
function twCheck(code, ext) {
  const full = (code + (ext && ext !== '-' ? ext : '')).replace(/\./g, '');
  if (code === 'TBD') return { tw_valid: null, tw_note: 'needs more information' };
  if (ext === '-') {
    const kids = Object.keys(tw.codes).filter(k => k.startsWith(full));
    return { tw_valid: null, tw_note: '7th character required', tw_children: kids.slice(0, 12).map(k => ({ code: k, name: tw.codes[k].name, zh: tw.codes[k].zh })) };
  }
  const hit = tw.codes[full];
  if (hit) return { tw_valid: true, tw_name: hit.name, tw_zh: hit.zh };
  const out = { tw_valid: false };
  // only list children when the code itself is a stem of 2023 codes (e.g. S93409 -> S93409A/D/S), not for a sibling like E11A
  const kids = Object.keys(tw.codes).filter(k => k.startsWith(full));
  if (kids.length) out.tw_children = kids.slice(0, 12).map(k => ({ code: k, name: tw.codes[k].name, zh: tw.codes[k].zh }));
  const conv = tw.conv[code + (ext || '')];
  if (conv) out.tw_prev = { since: conv[0], code: conv[1], zh: (tw.codes[conv[1].replace(/\./g, '')] || {}).zh || '' };
  return out;
}
const withTw = rows => rows.map(r => Object.assign({}, r, twCheck(r.code, r.ext)));

/* ---------- live I-MAGIC ---------- */
function liveQuery(id, answers) {
  const key = id + JSON.stringify(answers);
  if (liveCache.has(key)) return Promise.resolve(liveCache.get(key));
  const args = [path.join(ROOT, 'scripts', 'live.py'), id];
  if (answers.sex) args.push('--sex', answers.sex);
  if (answers.age_days !== undefined) args.push('--age-days', String(answers.age_days));
  if (answers.refine) args.push('--refine', answers.refine);
  if (answers.laterality) args.push('--laterality', answers.laterality);
  if (answers.episode) args.push('--episode', answers.episode);
  return new Promise((ok, bad) => {
    execFile(PYTHON, ['-X', 'utf8', ...args], { timeout: 90000, maxBuffer: 4e6 }, (err, stdout, stderr) => {
      if (err) return bad(new Error(stderr || err.message));
      try {
        const r = JSON.parse(stdout);
        const required = r.questions.filter(q => q.required);
        const pending = required[0] || r.questions[0] || null;
        const out = { mode: 'live', id, name: r.name, release: r.release, applied: r.applied, imagic_url: r.url,
          status: r.not_in_map ? 'not_in_map' : (pending ? 'need_info' : (r.rows.length <= 2 ? 'done' : 'multiple')),
          rows: withTw(r.rows), question: pending, questions: r.questions, notes: r.notes, advice: r.advice };
        liveCache.set(key, out); ok(out);
      } catch (e) { bad(new Error('bad live output: ' + e.message + ' ' + stdout.slice(0, 200))); }
    });
  });
}

/* ---------- helpers ---------- */
function parseAnswers(sp) {
  const a = {};
  if (sp.get('sex')) a.sex = sp.get('sex');
  if (sp.get('age_days')) a.age_days = Number(sp.get('age_days'));
  else if (sp.get('age')) a.age_days = Math.round(Number(sp.get('age')) * 365);
  for (const k of ['refine', 'laterality', 'episode']) if (sp.get(k)) a[k] = sp.get(k);
  return a;
}
function send(res, code, body, type) {
  const data = typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body, null, 1);
  res.writeHead(code, { 'Content-Type': type || 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' });
  res.end(data);
}
async function search(q) {
  const u = `https://tx.fhir.org/r4/ValueSet/$expand?url=http://snomed.info/sct?fhir_vs=isa/404684003&filter=${encodeURIComponent(q)}&count=20&_format=json`;
  const r = await fetch(u, { headers: { Accept: 'application/fhir+json' } });
  if (!r.ok) throw new Error('tx.fhir.org ' + r.status);
  const j = await r.json();
  return { query: q, source: 'tx.fhir.org SNOMED CT International (descendants of 404684003 Clinical finding)', total: j.expansion && j.expansion.total,
    results: ((j.expansion && j.expansion.contains) || []).map(c => ({ id: c.code, name: c.display, offline: !!rules.concepts.find(x => x.id === c.code) })) };
}

/* ---------- routes ---------- */
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;
  try {
    if (p === '/api/concepts') return send(res, 200, { source: rules.source, compiled: rules.compiled, concepts: rules.concepts.map(c => ({ id: c.id, name: c.name, not_in_map: !!c.not_in_map, default: c.default.map(r => r.code + r.ext), questions: c.questions.map(q => ({ type: q.type, required: q.required })) })) });
    let m = p.match(/^\/api\/map\/(\d{6,18})$/);
    if (m) {
      const id = m[1], answers = parseAnswers(url.searchParams), mode = url.searchParams.get('mode') || 'auto';
      if (mode !== 'live') {
        const r = resolve(rules, id, answers);
        if (r.status !== 'unknown' || mode === 'offline') return send(res, 200, Object.assign({ mode: 'offline', answers }, r, { rows: withTw(r.rows || []) }));
      }
      if (!LIVE) return send(res, 404, { status: 'unknown', id, error: 'not in offline rules and live mode is disabled' });
      return send(res, 200, Object.assign({ answers }, await liveQuery(id, answers)));
    }
    m = p.match(/^\/api\/tw\/([A-Za-z0-9.]+)$/);
    if (m) { const c = m[1].toUpperCase(); return send(res, 200, Object.assign({ code: c }, twCheck(c.replace(/[A-Z]$/, s => s), ''))); }
    if (p === '/api/search') { const q = (url.searchParams.get('q') || '').trim(); if (q.length < 2) return send(res, 400, { error: 'q too short' }); return send(res, 200, await search(q)); }
    if (p === '/api/health') return send(res, 200, { ok: true, concepts: rules.concepts.length, tw_codes: Object.keys(tw.codes).length, live: LIVE, python: PYTHON });
    // static
    let f = p === '/' ? '/index.html' : p;
    f = path.normalize(path.join(ROOT, 'public', f));
    if (!f.startsWith(path.join(ROOT, 'public')) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) return send(res, 404, { error: 'not found' });
    return send(res, 200, fs.readFileSync(f), MIME[path.extname(f)] || 'application/octet-stream');
  } catch (e) {
    return send(res, 500, { error: String(e.message || e) });
  }
});
server.listen(PORT, '127.0.0.1', () => console.log(`snomed-icd-mapper  http://localhost:${PORT}  (offline concepts: ${rules.concepts.length}, live: ${LIVE ? 'on via ' + PYTHON : 'off'})`));
