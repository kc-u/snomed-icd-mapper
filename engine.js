/* SNOMED CT → ICD-10-CM 判斷引擎（網頁與命令列共用）。
 * resolve(rules, sctId, answers) →
 *   {status:'unknown'}                                   概念不在規則資料裡
 *   {status:'need_info', question:{...}, rows, trace}    還要問一題
 *   {status:'done'|'multiple', rows:[...], trace}         rows ≤ 2 → done
 *   {status:'no_target', rows:[], trace}                   概念在對照表裡，但沒有對應的 ICD-10-CM 碼
 * answers：{sex:'male'|'female', age_days:數字, refine:SCTID|'none', laterality:ICD碼, episode:'A'|'D'|'S'}
 * 判斷順序和 I-MAGIC 相同：性別、年齡（病人資料）→ 更明確的診斷 → 左右側 → 第 7 碼。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.IMagic = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const EPISODE = [
    { value: 'A', label: '初次就醫（initial encounter）', hint: '還在積極治療' },
    { value: 'D', label: '後續就醫（subsequent encounter）', hint: '復原、追蹤期' },
    { value: 'S', label: '後遺症（sequela）', hint: '傷好了，處理留下的問題' },
  ];
  const sameRows = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const copy = rows => rows.map(r => ({ code: r.code, ext: r.ext, name: r.name }));

  function findConcept(rules, id) { return rules.concepts.find(c => c.id === String(id)); }

  function ageSegment(q, days) {
    for (const seg of q.intervals) {
      if (days >= seg.from_days && (seg.next_probe_days === null || days < seg.next_probe_days)) {
        return { seg, uncertain: days > seg.to_days };  // 落在兩個探測點之間：真正門檻位置未知
      }
    }
    return { seg: q.intervals[q.intervals.length - 1], uncertain: false };
  }

  function resolve(rules, id, answers) {
    answers = answers || {};
    const c = findConcept(rules, id);
    if (!c) return { status: 'unknown', id: String(id) };
    if (c.not_in_map) return { status: 'not_in_map', id: c.id, name: c.name, rows: [], trace: [], question: null, notes: {}, advice: {}, release: c.release };
    let rows = copy(c.default);
    const trace = [];
    const pending = [];
    const need = q => { if (!pending.length) pending.push(q); };

    for (const q of c.questions) {
      if (q.type === 'sex') {
        const differs = Object.values(q.outcomes).some(o => !sameRows(o, c.default));
        if (answers.sex && q.outcomes[answers.sex]) {
          rows = copy(q.outcomes[answers.sex]);
          trace.push({ step: 'sex', text: `性別 = ${answers.sex === 'male' ? '男' : '女'} → ${fmt(rows)}` });
        } else if (q.required || differs) {
          need({ type: 'sex', required: q.required, text: q.required ? '這個概念對男女對到不同的碼，請選性別' : '性別會影響結果，請選性別',
            options: [{ value: 'male', label: '男' }, { value: 'female', label: '女' }] });
        }
      } else if (q.type === 'age') {
        const differs = q.intervals.some(s => !sameRows(s.rows, c.default));
        if (typeof answers.age_days === 'number') {
          const { seg, uncertain } = ageSegment(q, answers.age_days);
          rows = copy(seg.rows);
          trace.push({ step: 'age', text: `年齡 ${fmtAge(answers.age_days)} → ${fmt(rows)}`,
            note: uncertain ? `門檻在 ${fmtAge(seg.to_days)} 到 ${fmtAge(seg.next_probe_days)} 之間，我們只探測到這兩點，這個年齡請到 I-MAGIC 再確認` : null });
        } else if (q.required || differs) {
          need({ type: 'age', required: q.required, text: q.required ? '要知道年齡才能給碼，請輸入年齡' : '年齡會影響結果，請輸入年齡',
            intervals: q.intervals.map(s => ({ from: fmtAge(s.from_days), rows: s.rows })) });
        }
      } else if (q.type === 'refine') {
        if (answers.refine && answers.refine !== 'none') {
          const o = q.options.find(x => x.value === answers.refine);
          if (o && o.rows) { rows = copy(o.rows); trace.push({ step: 'refine', text: `更明確的診斷：${o.label} → ${fmt(rows)}` }); }
        } else if (!answers.refine) {
          need({ type: 'refine', required: false, text: '有沒有下面哪個更明確的診斷？沒有就選「都不是」',
            options: q.options.filter(o => !o.not_applicable).map(o => ({ value: o.value, label: o.label, rows: o.rows })).concat([{ value: 'none', label: '都不是，維持原診斷' }]) });
        } else {
          trace.push({ step: 'refine', text: '更明確的診斷：都不是，維持原診斷' });
        }
      } else if (q.type === 'laterality') {
        if (answers.refine && answers.refine !== 'none') continue;  // 已換成更明確的診斷，左右側題不再適用
        if (answers.laterality) {
          const o = q.options.find(x => x.value === answers.laterality);
          if (o) { rows = rows.map(r => ({ code: o.value, ext: r.ext || '-', name: o.label })); trace.push({ step: 'laterality', text: `左右側：${o.label} → ${fmt(rows)}` }); }
        } else {
          need({ type: 'laterality', required: false, text: '哪一側？不知道就選「未明示」', options: q.options.map(o => ({ value: o.value, label: o.label })) });
        }
      }
    }
    // 第 7 碼：任何碼還帶 - 就要問就醫類型
    if (rows.some(r => r.ext === '-')) {
      if (answers.episode) {
        rows = rows.map(r => r.ext === '-' ? { code: r.code, ext: answers.episode, name: r.name } : r);
        trace.push({ step: 'episode', text: `第 7 碼：${EPISODE.find(e => e.value === answers.episode).label} → ${fmt(rows)}` });
      } else {
        need({ type: 'episode', required: true, text: '損傷碼一定要第 7 碼，請選這次是哪種就醫', options: EPISODE });
      }
    }
    rows = rows.map(r => Object.assign({}, r, tw(c, r)));
    const status = pending.length ? 'need_info' : (rows.length === 0 ? 'no_target' : rows.length <= 2 ? 'done' : 'multiple');
    return { status, id: c.id, name: c.name, rows, question: pending[0] || null, trace, notes: c.notes, advice: c.advice, release: c.release };
  }

  function tw(c, r) {
    const key = r.code + r.ext;
    const info = c.tw2023[key];
    if (info && !info.stem) return { tw_valid: info.valid, tw_name: info.name, tw_zh: info.zh };
    const stem = c.tw2023[r.code + '-'];
    if (stem && stem.children) {
      if (r.ext === '-') return { tw_valid: null, tw_name: '', tw_zh: '', tw_note: '缺第 7 碼' };
      const k = (r.code + r.ext).replace(/\./g, '');
      const child = stem.children[k];
      return child ? { tw_valid: true, tw_name: child.name, tw_zh: child.zh } : { tw_valid: false, tw_name: '', tw_zh: '' };
    }
    return { tw_valid: null, tw_name: '', tw_zh: '', tw_note: '未查核' };
  }

  function fmt(rows) { return rows.map(r => r.code + (r.ext || '')).join('、'); }
  function fmtAge(days) {
    if (days === null || days === undefined) return '?';
    if (days < 60) return `${days} 天`;
    if (days < 730) return `${Math.floor(days / 30)} 個月`;
    return `${Math.floor(days / 365)} 歲`;
  }
  return { resolve, findConcept, fmtAge, EPISODE };
}));
