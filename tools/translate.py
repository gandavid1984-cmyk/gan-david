#!/usr/bin/env python3
"""תרגום מוכן מראש לידיעות של "עיתון גן דוד" — בלי מודל שפה, בלי טוקנים.

שימוש:  python3 tools/translate.py [--days 30] [--langs en,ru,es] [--levels easy,medium,hard]

- קורא את data/news.json, ולכל ידיעה מ-N הימים האחרונים שחסר לה תרגום לשפה — מתרגם
  כותרת, הרמות המבוקשות ושלוש השאלות דרך שירות התרגום החינמי של Google (אותו שירות
  שהאתר משתמש בו בדף), ושומר בידיעה: "tr": {"en": {"title", "easy", "medium", "hard", "questions"}, ...}.
- מה שכבר מתורגם לא נשלח שוב. אם השירות לא עונה — מדלגים ומנסים בריצה הבאה.
- השירות אינו רשמי ועלול להיחסם; לכן בקשות בזו אחר זו עם המתנה קצרה, ו-3 ניסיונות.
"""
import json, os, sys, time, argparse, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS = os.path.join(ROOT, "data", "news.json")
URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=iw&tl={lang}&dt=t&q={q}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def g_once(text, lang):
    req = urllib.request.Request(URL.format(lang=lang, q=urllib.parse.quote(text)), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        j = json.loads(r.read().decode("utf-8"))
    out = "".join(x[0] for x in (j[0] or []) if x and x[0])
    if not out.strip():
        raise RuntimeError("empty")
    return out

def translate(text, lang):
    text = text or ""
    if not text.strip():
        return text
    if len(text) > 1500 and "\n" in text:  # טקסט ארוך — פסקה-פסקה
        return "\n".join(translate(p, lang) if p.strip() else "" for p in text.split("\n"))
    err = None
    for attempt in range(3):
        try:
            out = g_once(text, lang); time.sleep(0.4); return out
        except Exception as e:
            err = e; time.sleep(1.5 * (2 ** attempt))
    raise err

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--langs", default="en,ru,es")
    ap.add_argument("--levels", default="easy,medium,hard")
    a = ap.parse_args()
    langs = [l for l in a.langs.split(",") if l]
    levels = [l for l in a.levels.split(",") if l]

    d = json.load(open(NEWS, encoding="utf-8"))
    import datetime
    keep_from = (datetime.date.today() - datetime.timedelta(days=a.days - 1)).isoformat()
    try:
        g_once("בדיקה", "en")
    except Exception as e:
        print(f"שירות התרגום אינו נגיש ({type(e).__name__}: {e}) — לא שונה דבר."); return 3

    done = failed = skipped = 0
    for it in d["items"]:
        if it.get("date", "") < keep_from:
            it.pop("tr", None); continue
        tr = it.setdefault("tr", {})
        for lang in langs:
            cur = tr.get(lang) or {}
            need = [k for k in ["title", *levels] if it.get(k) and not cur.get(k)]
            if not cur.get("questions") and it.get("questions"):
                need.append("questions")
            if not need:
                skipped += 1; continue
            try:
                for k in need:
                    if k == "questions":
                        cur["questions"] = [translate(q, lang) for q in it["questions"]]
                    else:
                        cur[k] = translate(it[k], lang)
                tr[lang] = cur; done += 1
            except Exception as e:
                tr[lang] = cur  # שומרים את מה שכן הצליח
                failed += 1; print(f"נכשל: {it['id']} -> {lang}: {type(e).__name__}: {e}")
        # ניקוי שפות שאינן ברשימה
        for l in list(tr):
            if l not in langs: tr.pop(l)
        if not tr: it.pop("tr", None)
    json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"תורגמו: {done} | כבר היו: {skipped} | נכשלו: {failed}")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
