"""Turn harvested I-MAGIC results into rules.json for the engine.

usage: python scripts/compile.py
input:  data/imagic-harvest/<sct>.json, tw2023.json
output: rules.json  (per concept: default codes, questions, outcome of every answer, Taiwan 2023 check)
"""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARV = ROOT / "data" / "imagic-harvest"
TW = json.loads((ROOT / "tw2023.json").read_text(encoding="utf-8"))
EPI = {"initial encounter": "A", "subsequent encounter": "D", "sequela": "S"}


def rows(st):
    return [{"code": r["code"], "ext": r["ext"], "name": r["name"]} for r in st["rows"]]


def tw(code, ext):
    """Taiwan 2023 edition check. ext '-' = 7th character still missing: list the 2023 codes under the stem."""
    if code == "TBD":
        return {"valid": None, "name": "", "zh": ""}
    nd = lambda s: s.replace(".", "")  # noqa: E731
    if ext == "-":
        kids = sorted(k for k in TW["codes"] if k.startswith(nd(code)))
        return {"valid": bool(kids), "stem": True, "name": "", "zh": "", "children": {k: TW["codes"][k] for k in kids[:12]}}
    hit = TW["codes"].get(nd(code + ext))
    out = {"valid": bool(hit), "name": hit["name"] if hit else "", "zh": hit["zh"] if hit else ""}
    if not hit and (code + ext) in TW["conv"]:
        since, prev = TW["conv"][code + ext]
        out.update({"since": since, "prev": prev, "prev_zh": TW["codes"].get(nd(prev), {}).get("zh", "")})
    return out


def age_intervals(variants):
    """Merge age probes with identical results into intervals; the real threshold lies between to_days and next_probe_days."""
    probes = sorted((v["age_days"], rows(v["result"])) for v in variants if v["kind"] == "age")
    out = []
    for d, r in probes:
        if out and out[-1]["rows"] == r:
            out[-1]["to_days"] = d
        else:
            out.append({"from_days": d, "to_days": d, "rows": r})
    for i, seg in enumerate(out):
        seg["next_probe_days"] = out[i + 1]["from_days"] if i + 1 < len(out) else None
    return out


def compile_one(rec, names):
    base = rec["base"]
    vs = rec["variants"]
    c = {"id": rec["sct"], "name": base["problems"][0]["name"] if base["problems"] else names.get(rec["sct"]), "release": base["release"],
         "not_in_map": not base["problems"], "default": rows(base), "questions": [], "notes": base["notes"],
         "advice": {"advice": base["advice"]} if base["advice"] else {}, "fetched": rec["fetched"]}
    for q in base["questions"]:
        opt_names = {o["name"] for o in q["options"]}
        radios = [o for o in q["options"] if o["type"] == "radio"]
        n = radios[0]["name"] if radios else ""
        if "f" in opt_names:
            c["questions"].append({"type": "sex", "required": q["required"], "heading": q["heading"],
                                   "outcomes": {v["label"]: rows(v["result"]) for v in vs if v["kind"] == "sex"}})
        elif "dob" in opt_names:
            c["questions"].append({"type": "age", "required": q["required"], "heading": q["heading"], "intervals": age_intervals(vs)})
        elif n.startswith("laterality-"):
            c["questions"].append({"type": "laterality", "required": q["required"], "heading": q["heading"], "text": q["text"],
                                   "options": [{"value": o["value"], "label": o["label"],
                                                "rows": next((rows(v["result"]) for v in vs if v["kind"] == "laterality" and v["value"] == o["value"]), None)} for o in radios]})
        elif n.startswith("episode-"):
            c["questions"].append({"type": "episode", "required": q["required"], "heading": q["heading"],
                                   "options": [{"value": o["value"], "suffix": EPI[o["value"]], "label": o["label"],
                                                "rows": next((rows(v["result"]) for v in vs if v["kind"] == "episode" and v["value"] == o["value"]), None)} for o in radios]})
        elif n.startswith("comorbidity-"):
            c["questions"].append({"type": "refine", "required": q["required"], "heading": q["heading"], "text": q["text"],
                                   "options": [{"value": o["value"], "label": o["label"], "not_applicable": o["value"] == rec["sct"],
                                                "rows": next((rows(v["result"]) for v in vs if v["kind"] == "refine" and v["value"] == o["value"]), None)} for o in radios]})
    codes = {}

    def add(rs):
        for r in rs or []:
            codes.setdefault((r["code"], r["ext"]), r["name"])
    add(c["default"])
    for q in c["questions"]:
        for o in q.get("options", []):
            add(o["rows"])
            if q["type"] == "laterality":
                codes.setdefault((o["value"], "-"), o["label"])
        for rs in q.get("outcomes", {}).values():
            add(rs)
        for seg in q.get("intervals", []):
            add(seg["rows"])
    c["tw2023"] = {f"{k[0]}{k[1]}": {"name_us": v, **tw(*k)} for k, v in codes.items()}
    return c


def main():
    old = json.loads((ROOT / "rules.json").read_text(encoding="utf-8")) if (ROOT / "rules.json").exists() else {"concepts": []}
    names = {c["id"]: c["name"] for c in old["concepts"] if c.get("name")}  # keep names of concepts I-MAGIC does not show
    concepts = [compile_one(json.loads(p.read_text(encoding="utf-8")), names) for p in sorted(HARV.glob("*.json")) if not p.name.startswith("_")]
    data = {"source": "NLM I-MAGIC demo (SNOMED CT to ICD-10-CM Map release 20260901), reconstructed from per-condition queries",
            "compiled": dt.date.today().isoformat(), "tw_codes": "CMS ICD-10-CM FY2023 codes file (Taiwan NHI edition from 2025-01-01)", "concepts": concepts}
    (ROOT / "rules.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in concepts:
        bad = [k for k, v in c["tw2023"].items() if v["valid"] is False]
        print(c["id"], c["name"], [r["code"] + r["ext"] for r in c["default"]], [q["type"] + ("*" if q["required"] else "") for q in c["questions"]], "TW missing: " + ",".join(bad) if bad else "")
    print(len(concepts), "concepts")


if __name__ == "__main__":
    main()
