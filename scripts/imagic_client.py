"""Client for the NLM I-MAGIC demo (https://imagic.nlm.nih.gov/imagic/).

I-MAGIC runs the SNOMED CT to ICD-10-CM Map with patient context (sex, date of birth) and
asks follow-up questions when the map needs more information. Every form on the demo page is
submitted with GET, so a whole dialogue can be replayed with query parameters.

parse(html) -> dict   structured view of one result page
Session                one I-MAGIC session (the demo keeps a problem list in the session)
"""
import datetime as dt
import html as _html
import re
import time

import requests

BASE_URL = "https://imagic.nlm.nih.gov/imagic/"
UA = {"User-Agent": "Mozilla/5.0 (snomed-icd-mapper; personal study project)"}
DEFAULTS = {"v": "6", "from-tab": "demo", "pat": "My Patient", "f": "", "dob": ""}
SEX = {"male": "0", "female": "1"}
EPISODE = {"A": "initial encounter", "D": "subsequent encounter", "S": "sequela"}


def clean(s):
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def parse(t):
    """One I-MAGIC result page -> codes, follow-up questions, ICD notes, map advice."""
    rel = re.search(r"Using the (\d+) release", t)
    sec = t[t.find('id="mapping"'):t.find("<footer")]
    st = {"release": rel.group(1) if rel else None, "problems": [], "rows": [], "questions": [], "notes": {}, "advice": []}
    for m in re.finditer(r'<span class="sct-name">(.*?)</span> \(<span class="code">(\d+)</span>\)', sec):
        st["problems"].append({"id": m.group(2), "name": clean(m.group(1))})
    for m in re.finditer(r'<span class="icd-code">(.*?)</span></th><td[^>]*>(.*?)</td>', sec, re.S):
        leaf = re.search(r'icd-leaf">(.*?)<', m.group(1))
        filler = re.search(r'icd-filler">(.*?)<', m.group(1))
        ext = re.search(r'icd-ext[^"]*">(.*?)<', m.group(1))
        code = (clean(leaf.group(1)) if leaf else clean(m.group(1))) + (clean(filler.group(1)) if filler else "")
        st["rows"].append({"code": code, "ext": clean(ext.group(1)) if ext else "", "name": clean(m.group(2))})
    head = None
    for tr in re.finditer(r'<tr class="([^"]*qrow[^"]*)"[^>]*>(.*?)</tr>', sec, re.S):
        cls, body = tr.group(1), tr.group(2)
        th = re.search(r"<th[^>]*>(.*?)</th>", body, re.S)
        if th:
            head = clean(th.group(1))
            continue
        if head is None:
            continue
        if head.startswith("ICD notes"):
            st["notes"].setdefault(head, []).append(clean(body))
        elif head == "Map Advice":
            st["advice"].append(clean(body))
        else:
            opts = [{"name": i.group(1), "type": i.group(2), "value": i.group(3), "label": clean(i.group(4) or "")}
                    for i in re.finditer(r'<input name="([^"]+)" type="(radio|checkbox|text)"(?: value="([^"]*)")?[^>]*>(?:<span>(.*?)</span>)?', body, re.S)]
            if '<select name="f">' in body:
                opts.append({"name": "f", "type": "select", "value": None, "label": "sex"})
            if 'name="dob"' in body:
                opts.append({"name": "dob", "type": "text", "value": None, "label": "date of birth"})
            if opts:
                st["questions"].append({"heading": head, "required": "qrow-required" in cls,
                                        "text": clean(re.sub(r"<ul.*?</ul>", "", body, flags=re.S))[:200], "options": opts})
        head = None
    return st


def question_type(q):
    h = q["heading"]
    names = {o["name"] for o in q["options"]}
    if "f" in names:
        return "sex"
    if "dob" in names:
        return "age"
    if "Laterality" in h:
        return "laterality"
    if "Episode" in h:
        return "episode"
    if "Problem Refinement" in h or any(n.startswith("comorbidity-") for n in names):
        return "refine"
    return "other"


def dob_from_age_days(days, today=None):
    return ((today or dt.date.today()) - dt.timedelta(days=int(days))).isoformat()


class Session:
    """A fresh I-MAGIC session. add(sct) puts the concept on the problem list; submit() answers a form."""

    def __init__(self, sleep=0.4):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.s.get(BASE_URL + "code/map", timeout=60)
        self.sleep = sleep
        self.last_url = None
        time.sleep(sleep)

    def _get(self, params):
        r = self.s.get(BASE_URL, params=params, timeout=60)
        r.raise_for_status()
        self.last_url = r.url
        time.sleep(self.sleep)
        return r.text

    def add(self, sct, f="", dob=""):
        return self._get({**DEFAULTS, "f": f, "dob": dob, "pdraft": sct, "pdone": "1"})

    def submit(self, sct, answers, f="", dob=""):
        return self._get({**DEFAULTS, "f": f, "dob": dob, "problems": sct, **answers, "pdone": "1"})
