"""Ask I-MAGIC live for one concept with the answers given so far; print the result as JSON.

usage: python scripts/live.py <SCTID> [--sex male|female] [--age-days N] [--refine SCTID|none]
                              [--laterality ICD] [--episode A|D|S]
output: {"mode":"live", "release", "name", "not_in_map", "rows":[{code,ext,name}],
         "questions":[{type, required, text, options:[{value,label}]}], "notes", "advice", "applied", "url"}
The questions left in the output are the ones I-MAGIC still shows after the answers were applied.
"""
import argparse
import json
import sys

from imagic_client import EPISODE, SEX, Session, dob_from_age_days, parse, question_type


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sct")
    ap.add_argument("--sex", choices=["male", "female"])
    ap.add_argument("--age-days", type=int)
    ap.add_argument("--refine")
    ap.add_argument("--laterality")
    ap.add_argument("--episode", choices=["A", "D", "S"])
    a = ap.parse_args()

    f = SEX.get(a.sex, "")
    dob = dob_from_age_days(a.age_days) if a.age_days is not None else ""
    ses = Session()
    st = parse(ses.add(a.sct, f, dob))
    applied = {k: v for k, v in {"sex": a.sex, "age_days": a.age_days}.items() if v is not None}
    sct = a.sct

    def radios(state, qtype):
        for q in state["questions"]:
            if question_type(q) == qtype:
                return [o for o in q["options"] if o["type"] == "radio"]
        return []

    # 1 problem refinement (replace the problem with the more specific concept)
    if a.refine and a.refine != "none":
        opts = radios(st, "refine")
        if any(o["value"] == a.refine for o in opts):
            n = opts[0]["name"]
            st = parse(ses.submit(sct, {n: a.refine, "replace": n}, f, dob))
            applied["refine"] = a.refine
            sct = st["problems"][0]["id"] if st["problems"] else sct
    elif a.refine == "none":
        applied["refine"] = "none"
    # 2 laterality and episode in one submission (names come from the current page)
    sub = {}
    if a.laterality:
        opts = radios(st, "laterality")
        if any(o["value"] == a.laterality for o in opts):
            sub[opts[0]["name"]] = a.laterality
            applied["laterality"] = a.laterality
    if a.episode:
        opts = radios(st, "episode")
        if opts:
            sub[opts[0]["name"]] = EPISODE[a.episode]
            applied["episode"] = a.episode
    if sub:
        st = parse(ses.submit(sct, sub, f, dob))

    questions = []
    for q in st["questions"]:
        t = question_type(q)
        if t in applied or (t == "refine" and "refine" in applied):
            continue
        opts = [o for o in q["options"] if o["type"] == "radio"]
        if t == "sex":
            options = [{"value": "male", "label": "male"}, {"value": "female", "label": "female"}]
        elif t == "age":
            options = []
        elif t == "episode":
            options = [{"value": k, "label": v} for k, v in EPISODE.items()]
        elif t == "refine":
            options = [{"value": o["value"], "label": o["label"]} for o in opts if o["value"] != sct] + [{"value": "none", "label": "none of these"}]
        else:
            options = [{"value": o["value"], "label": o["label"]} for o in opts]
        questions.append({"type": t, "required": q["required"], "text": q["text"], "options": options})

    out = {"mode": "live", "release": st["release"], "id": a.sct, "name": st["problems"][0]["name"] if st["problems"] else None,
           "not_in_map": not st["problems"], "rows": st["rows"], "questions": questions,
           "notes": st["notes"], "advice": st["advice"], "applied": applied, "url": ses.last_url}
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
