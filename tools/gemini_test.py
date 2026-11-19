#!/usr/bin/env python3
"""בדיקה זמנית: תרגום ידיעות היום עם Gemini API (רמה חינמית), להשוואה מול Google."""
import json, os, sys, time, urllib.request, urllib.error
KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not KEY:
    print("חסר הסוד GEMINI_API_KEY ב-GitHub (Settings > Secrets and variables > Actions)."); sys.exit(2)
BASE = "https://generativelanguage.googleapis.com/v1beta"
def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read())
try:
    models = [m for m in call("/models?pageSize=200")["models"] if "generateContent" in m.get("supportedGenerationMethods", [])]
except urllib.error.HTTPError as e:
    print("שגיאה ברשימת המודלים:", e.code, e.read()[:300]); sys.exit(3)
names = [m["name"].split("/")[-1] for m in models]
print("מודלים זמינים:", ", ".join(names))
pick = os.environ.get("GEMINI_MODEL") or next((n for n in names if "flash-lite" in n and "preview" not in n and "image" not in n and "tts" not in n), None) or next((n for n in names if "flash" in n and "image" not in n and "tts" not in n), names[0])
print("מודל שנבחר:", pick)
d = json.load(open("data/news.json", encoding="utf-8"))
items = [i for i in d["items"] if i["date"] == "2026-11-19"]
LN = {"en": "English", "ru": "Russian", "es": "Spanish"}
def gem(it, lang):
    src = {"title": it["title"], "text": it["medium"], "questions": it["questions"]}
    prompt = (f"Translate this Hebrew news item into {LN[lang]}. The readers are elderly people, so keep the language simple, warm and natural. "
              "Keep every fact, number, date and name exactly as in the source; use the standard spelling of Israeli names, teams, places and institutions in the target language. "
              "Do not add, omit or explain anything. Return JSON: {\"title\": string, \"text\": string, \"questions\": [string, string, string]}.\n\n" + json.dumps(src, ensure_ascii=False))
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    for w in [0, 20, 60, 120]:
        time.sleep(w)
        try:
            r = call(f"/models/{pick}:generateContent", body)
            return json.loads(r["candidates"][0]["content"]["parts"][0]["text"]), r.get("usageMetadata", {})
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} {e.read()[:200]!r} (ניסיון חוזר)")
        except Exception as e:
            print("  שגיאה:", type(e).__name__, e)
    return None, {}
ok = fail = 0; toks = 0
for n, it in enumerate(items):
    print("\n########", it["id"], "|", it["title"])
    print("HE:", it["medium"])
    for lang in ("en", "ru", "es"):
        out, u = gem(it, lang); time.sleep(6)
        if not out: fail += 1; print(f"[{lang}] נכשל"); continue
        ok += 1; toks += u.get("totalTokenCount", 0)
        print(f"[{lang}] GEMINI title: {out.get('title')}\n[{lang}] GEMINI text: {out.get('text')}\n[{lang}] GEMINI q: {out.get('questions')}")
        if n < 3: print(f"[{lang}] GOOGLE text: {it['tr'][lang]['medium']}")
print(f"\nהצליחו {ok}, נכשלו {fail}, סך טוקנים {toks}")
