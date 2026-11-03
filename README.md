# snomed-icd-mapper

Interactive SNOMED CT → ICD-10-CM mapper, following the question-and-answer logic of NLM's
[I-MAGIC](https://imagic.nlm.nih.gov/imagic/) demo, with a Taiwan check against the ICD-10-CM
2023 edition. A local web page for people and a JSON API for programs, sharing one engine.

個人練習專案。輸入一個 SNOMED CT 概念，照 NLM I-MAGIC 的規則一題一題問（性別、年齡、更明確的診斷、左右側、第 7 碼），
問到剩一個 ICD-10-CM 碼，再查這個碼台灣 2023 年版有沒有、附健保署中文名。

## Run

```
node server.js            # http://localhost:8765
```

Requirements: Node 18+ (uses built-in `http` and `fetch`, no npm packages). For live I-MAGIC
queries, Python 3 with `requests` (`pip install requests`); set `PYTHON` if it is not on PATH.

```
PYTHON=C:\path\to\python.exe node server.js     # choose the Python used for live queries
NO_LIVE=1 node server.js                        # offline rules only
PORT=9000 node server.js
```

## How it works

```
browser ──┐
          ├─► server.js ─► engine.js + rules.json      offline rules (44 concepts)
agent  ───┘       │       ─► scripts/live.py            live query to I-MAGIC for any other concept
                  │       ─► tw2023.json                Taiwan 2023-edition check + Chinese names
                  └─► tx.fhir.org $expand               name search
```

- **Offline rules** (`rules.json`): for each concept, what I-MAGIC answered under every
  condition (male/female, 23 ages, every laterality / episode / refinement option). Rebuilt with
  `scripts/harvest.py` and `scripts/compile.py`. This is *not* the official NLM map file (that
  needs a UMLS account); once the file is available, `compile.py` can read it instead and the
  engine stays the same.
- **Live mode**: a concept not in the offline rules is sent to I-MAGIC with the answers given so
  far; the reply is the official result at that moment. Needs network access to NLM, ~1–2 s per step.
- **Engine** (`engine.js`): resolves in I-MAGIC's order: sex, age → more specific diagnosis →
  laterality → 7th character. Returns `done` or `need_info` with the next question.
- **Taiwan check** (`tw2023.json`): every result code is checked against the CMS FY2023 code file
  (Taiwan NHI adopted the 2023 edition on 2025-01-01). Valid codes get the Chinese description from
  the NHI 2023 query system; invalid ones get the sibling codes of the same stem and the previous
  code from the CMS FY2027 conversion table (e.g. E11.A → E11.9).

## API

| Method | Path | Returns |
|---|---|---|
| GET | `/api/map/{sctid}?sex=&age=&age_days=&refine=&laterality=&episode=&mode=` | mapping result; `mode` = `auto` (default), `offline`, `live` |
| GET | `/api/search?q=ankle sprain` | SNOMED CT concepts by (English) name, via tx.fhir.org |
| GET | `/api/tw/{icd}` | Taiwan 2023 check for one ICD-10-CM code |
| GET | `/api/concepts` | concepts covered by the offline rules |
| GET | `/api/health` | status |

Agent loop: call `/api/map/{id}`; while `status` is `need_info`, read `question` (type `sex`,
`age`, `refine`, `laterality`, `episode` with `options`), answer it as a query parameter and call
again; stop at `done` (1–2 codes), `multiple`, `no_target` (concept is in the map but has no target
code), `not_in_map` (I-MAGIC does not have the concept) or `unknown` (not in offline rules and live
mode disabled). A `not_in_map` reply carries `sct` from tx.fhir.org: `inactive` tells whether the
concept has been retired in SNOMED CT International (the usual reason — I-MAGIC only maps active
concepts), with `effective_time` of that change. Search by name to find the current concept.

```
GET /api/map/8619003                 → need_info, question.type = sex
GET /api/map/8619003?sex=female      → done, N97.9 (tw_valid true, tw_zh 女性不孕)
GET /api/map/44465007?laterality=S93.402&episode=D → done, S93.402D
```

Row fields: `code`, `ext` (7th character), `name` (US), `tw_valid`, `tw_name`, `tw_zh`,
`tw_children`, `tw_prev`.

## Scripts

```
python scripts/harvest.py [sctid ...]   # query I-MAGIC for each concept under every condition → data/imagic-harvest/
python scripts/compile.py               # harvest → rules.json (needs tw2023.json for the Taiwan check)
node scripts/verify.js                  # engine must reproduce every harvested I-MAGIC answer
python scripts/live.py 44465007 --laterality S93.402 --episode D
```

## Data sources

- NLM I-MAGIC demo, SNOMED CT to ICD-10-CM Map release 20260901 — https://imagic.nlm.nih.gov/imagic/
- SNOMED CT to ICD-10 Map Specification (mapRule grammar) — https://docs.snomed.org/
- CMS ICD-10-CM FY2023 code descriptions — https://www.cms.gov/files/zip/2023-code-descriptions-tabular-order.zip
- CMS ICD-10-CM FY2027 conversion table — https://www.cms.gov/files/zip/2027-conversion-table.zip
- Taiwan NHI 2023 ICD-10-CM query system (Chinese descriptions) — https://www.nhi.gov.tw/ch/cp-14313-ee75b-3051-1.html
- tx.fhir.org (SNOMED CT International) for name search

SNOMED CT is owned by SNOMED International; use of SNOMED CT content is subject to its licence.
ICD-10-CM is published by CDC/NCHS and CMS. This project only stores lookup results and code lists
from the public sources above; no patient data.

## Limits

- Offline rules cover 44 concepts; age thresholds were probed, not read from the map file.
- One concept at a time. I-MAGIC lets concepts on the same problem list refine each other; not done here.
- Live mode depends on the I-MAGIC demo page staying as it is.

## Licence

MIT
