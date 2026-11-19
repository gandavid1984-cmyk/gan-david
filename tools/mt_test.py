#!/usr/bin/env python3
"""בדיקת איכות זמנית: מודלי תרגום פתוחים (רצים בתוך GitHub Actions, בלי שירות חיצוני) מול התרגום של Google שכבר שמור."""
import json, re, sys, time, torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

d = json.load(open("data/news.json", encoding="utf-8"))
byid = {i["id"]: i for i in d["items"]}
SAMPLES = [("2026-11-19-sport-1", "medium"), ("2026-11-19-world-1", "medium"),
           ("2026-11-19-birthdays-1", "medium"), ("2026-11-19-health-1", "hard")]
texts = []
for iid, lv in SAMPLES:
    it = byid[iid]; texts.append((f"{iid}/{lv}", it[lv], {l: it["tr"][l][lv] for l in ("en", "ru", "es")}))
qs = byid["2026-11-19-sport-1"]["questions"]

def sents(t):
    out = []
    for para in t.split("\n"):
        out += [x.strip() for x in re.split(r"(?<=[.!?:])\s+", para) if x.strip()]
    return out

def run(model_name, src, tgt, texts, forced=None, batch=8):
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(model_name, **({"src_lang": src} if src else {}))
    m = AutoModelForSeq2SeqLM.from_pretrained(model_name).eval()
    res = []
    for s in texts:
        parts = sents(s); outs = []
        for i in range(0, len(parts), batch):
            enc = tok(parts[i:i+batch], return_tensors="pt", padding=True, truncation=True, max_length=256)
            kw = dict(num_beams=4, max_new_tokens=256)
            if forced: kw["forced_bos_token_id"] = tok.convert_tokens_to_ids(forced)
            with torch.no_grad(): g = m.generate(**enc, **kw)
            outs += tok.batch_decode(g, skip_special_tokens=True)
        res.append(" ".join(outs))
    print(f"[{model_name}] {time.time()-t0:.0f}s", flush=True)
    return res

allhe = [t for _, t, _ in texts] + qs
print("=== A: pivot via English (opus-mt) ===", flush=True)
en = run("Helsinki-NLP/opus-mt-tc-big-he-en", None, None, allhe)
ru = run("Helsinki-NLP/opus-mt-en-ru", None, None, en)
es = run("Helsinki-NLP/opus-mt-en-es", None, None, en)
print("=== B: NLLB direct ===", flush=True)
nen = run("facebook/nllb-200-distilled-1.3B", "heb_Hebr", None, allhe, forced="eng_Latn")
nru = run("facebook/nllb-200-distilled-1.3B", "heb_Hebr", None, allhe, forced="rus_Cyrl")
nes = run("facebook/nllb-200-distilled-1.3B", "heb_Hebr", None, allhe, forced="spa_Latn")

for k, (name, he, goog) in enumerate(texts):
    print("\n########", name)
    print("HE :", he[:700].replace("\n", " | "))
    for l, a, b, g in (("en", en[k], nen[k], goog["en"]), ("ru", ru[k], nru[k], goog["ru"]), ("es", es[k], nes[k], goog["es"])):
        print(f"--- {l} GOOGLE:", g[:700].replace("\n", " | "))
        print(f"--- {l} A-pivot :", a[:700])
        print(f"--- {l} B-nllb  :", b[:700])
print("\n######## questions (sport-1)")
for j, q in enumerate(qs):
    k = len(texts) + j
    print("HE:", q); print(" A en/ru/es:", en[k], "|", ru[k], "|", es[k]); print(" B en/ru/es:", nen[k], "|", nru[k], "|", nes[k])
