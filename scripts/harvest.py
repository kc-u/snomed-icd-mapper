"""Query I-MAGIC for each concept under every condition and save the raw pages plus a parsed JSON.

usage: python scripts/harvest.py [sctid ...]      (default: every concept already in rules.json)
output: data/imagic-harvest/<sct>/*.html, data/imagic-harvest/<sct>.json
Pages already on disk are not fetched again, so re-running after a parser change only re-parses.
"""
import datetime as dt
import json
import sys
from pathlib import Path

from imagic_client import Session, parse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "imagic-harvest"
TODAY = dt.date.today()
# age probes in days, both sides of the thresholds the map commonly uses
AGE_DAYS = [0, 27, 28, 29, 60, 90, 180, 364, 365, 2 * 365, 5 * 365, 11 * 365, 12 * 365, 14 * 365, 15 * 365, 17 * 365,
            18 * 365, 20 * 365, 49 * 365, 50 * 365, 64 * 365, 65 * 365, 80 * 365]


def dob(days):
    return (TODAY - dt.timedelta(days=days)).isoformat()


class Fetcher:
    def __init__(self, sct, folder):
        self.sct, self.folder = sct, folder

    def fetch(self, tag, f="", dob="", submit=None):
        path = self.folder / f"{tag}.html"
        if path.exists():
            return parse(path.read_text(encoding="utf-8"))
        s = Session()
        t = s.add(self.sct, f, dob)
        if submit:
            t = s.submit(self.sct, submit, f, dob)
        path.write_text(t, encoding="utf-8")
        return parse(t)


def harvest(sct):
    folder = OUT / sct
    folder.mkdir(parents=True, exist_ok=True)
    c = Fetcher(sct, folder)
    rec = {"sct": sct, "fetched": TODAY.isoformat(), "base": c.fetch("base"), "variants": []}
    qs = rec["base"]["questions"]
    names = {o["name"] for q in qs for o in q["options"]}
    if "f" in names:
        for f, lab in [("0", "male"), ("1", "female")]:
            rec["variants"].append({"kind": "sex", "f": f, "label": lab, "result": c.fetch(f"sex_{lab}", f=f)})
    if "dob" in names:
        for d in AGE_DAYS:
            rec["variants"].append({"kind": "age", "age_days": d, "dob": dob(d), "result": c.fetch(f"age_{d:05d}d", dob=dob(d))})
    groups = {}
    for q in qs:
        for o in q["options"]:
            if o["type"] == "radio":
                groups.setdefault(o["name"], []).append(o)
    lat = [n for n in groups if n.startswith("laterality-")]
    epi = [n for n in groups if n.startswith("episode-")]
    for n in lat:
        for o in groups[n]:
            sub = {n: o["value"]}
            if epi:
                sub[epi[0]] = "initial encounter"
            rec["variants"].append({"kind": "laterality", "value": o["value"], "label": o["label"], "episode": "initial encounter" if epi else None,
                                    "result": c.fetch(f"lat_{o['value'].replace('.', '_')}", submit=sub)})
    for n in epi:
        for o in groups[n]:
            rec["variants"].append({"kind": "episode", "value": o["value"], "result": c.fetch(f"epi_{o['value'].split()[0]}", submit={n: o["value"]})})
    for n in groups:
        if n.startswith("comorbidity-"):
            for o in groups[n]:
                if o["value"] == sct:
                    continue
                rec["variants"].append({"kind": "refine", "value": o["value"], "label": o["label"],
                                        "result": c.fetch(f"refine_{o['value']}", submit={n: o["value"], "replace": n})})
    (OUT / f"{sct}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def main():
    ids = sys.argv[1:] or [c["id"] for c in json.loads((ROOT / "rules.json").read_text(encoding="utf-8"))["concepts"]]
    for i, sct in enumerate(ids, 1):
        rec = harvest(sct)
        b = rec["base"]
        print(f"{i}/{len(ids)} {sct} {b['problems'][0]['name'] if b['problems'] else '(not in map)'} -> "
              f"{[r['code'] + r['ext'] for r in b['rows']]} q={[q['heading'] for q in b['questions']]} variants={len(rec['variants'])}", flush=True)


if __name__ == "__main__":
    main()
