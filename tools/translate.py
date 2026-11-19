#!/usr/bin/env python3
"""תרגום מוכן מראש לידיעות של "עיתון גן דוד" — בלי מודל שפה, בלי טוקנים.

שימוש:  python3 tools/translate.py [--days 30] [--langs en,ru,es] [--levels easy,medium,hard]

- קורא את data/news.json, ולכל ידיעה מ-N הימים האחרונים שחסר לה תרגום לשפה — מתרגם
  כותרת, הרמות המבוקשות ושלוש השאלות דרך שירות התרגום החינמי של Google (אותו שירות
  שהאתר משתמש בו בדף), ושומר בידיעה: "tr": {"en": {"title", "easy", "medium", "hard", "questions"}, ...}.
- מה שכבר מתורגם לא נשלח שוב. אם השירות לא עונה — מדלגים ומנסים בריצה הבאה.
- השירות אינו רשמי ועלול להיחסם (429). לכן הקטעים מאוגדים לקבוצות של עד ~3500 תווים (בקשת POST אחת לקבוצה,
  במקום בקשה לכל כותרת/רמה/שאלה), עם סימוני הפרדה שנבדקים אחרי התרגום, המתנה בין בקשות וניסיונות חוזרים.
- אם נשאר משהו שלא תורגם — הסקריפט מסיים בקוד שגיאה, וההרצה ב-GitHub מסומנת ככשלון (ולא נבלעת בשקט).
"""
import json, os, re, sys, time, argparse, datetime, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS = os.path.join(ROOT, "data", "news.json")
URL_POST = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=iw&tl={lang}&dt=t"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


MAXCH = 3500      # תווים מקסימליים בבקשה אחת
MAXSEG = 40       # קטעים מקסימליים בבקשה אחת
PAUSE = 3.0       # המתנה בין בקשות (שניות)
WAITS = [10, 40, 120, 240]   # המתנה בין ניסיונות חוזרים
MARK = "[[#{}#]]"
MARK_RE = re.compile(r"\[\s*\[\s*#\s*(\d+)\s*#\s*\]\s*\]")

def g_post(text, lang):
    data = urllib.parse.urlencode({"q": text}).encode()
    url = URL_POST.format(lang=lang)
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        j = json.loads(r.read().decode("utf-8"))
    out = "".join(x[0] for x in (j[0] or []) if x and x[0])
    if not out.strip():
        raise RuntimeError("empty")
    return out

def g_retry(text, lang):
    err = None
    for w in [0] + WAITS:
        if w: time.sleep(w)
        try:
            out = g_post(text, lang); time.sleep(PAUSE); return out
        except Exception as e:
            err = e
    raise err

HEB = re.compile(r"[\u0590-\u05ff]")
def heb_leak(src, out):
    """התרגום עדיין בעברית (בחלקו הגדול) — כלומר לא תורגם באמת."""
    if not HEB.search(src): return False
    letters = re.findall(r"[A-Za-z\u0400-\u04ff\u0590-\u05ff]", out)
    return bool(letters) and len(HEB.findall(out)) / len(letters) > 0.15

def prep(text):
    """ניסוחים שהמתרגם מתקשה בהם (למשל "נמקו" יוצא כ-Nemko)."""
    return text.replace("נמקו", "הסבירו למה")

def translate_one(text, lang):
    """קטע בודד; ארוך מדי — פסקה-פסקה."""
    if not text.strip(): return text
    if len(text) > MAXCH and "\n" in text:
        return "\n".join(translate_one(p, lang) if p.strip() else "" for p in text.split("\n"))
    return g_retry(text, lang)

def translate_batch(segs, lang):
    """segs: [(id, text)] -> {id: translated}. מאגד, מוודא סימונים, ובמקרה של אי-התאמה מפצל."""
    if len(segs) == 1:
        i, t = segs[0]
        for _ in range(3):
            out = translate_one(prep(t), lang)
            if not heb_leak(t, out): return {i: out}
            time.sleep(PAUSE * 2)
        raise RuntimeError("התרגום חזר בעברית")
    joined = "\n".join(MARK.format(i) + "\n" + prep(t) for i, t in segs)
    try:
        out = g_retry(joined, lang)
        ms = list(MARK_RE.finditer(out))
        ids = [int(m.group(1)) for m in ms]
        if ids == [i for i, _ in segs]:
            res = {}
            for k, m in enumerate(ms):
                end = ms[k + 1].start() if k + 1 < len(ms) else len(out)
                res[ids[k]] = out[m.end():end].strip("\n").strip()
            if all((res[i].strip() or not t.strip()) and not heb_leak(t, res[i]) for i, t in segs):
                return res
        print(f"  אי-התאמה בסימונים ({len(segs)} קטעים) — מפצל")
    except Exception as e:
        print(f"  כשל בקבוצה של {len(segs)} קטעים: {type(e).__name__}: {e} — מפצל")
    mid = len(segs) // 2
    res = translate_batch(segs[:mid], lang)
    res.update(translate_batch(segs[mid:], lang))
    return res

def make_batches(segs):
    batches, cur, n = [], [], 0
    for s in segs:
        L = len(s[1]) + 12
        if cur and (n + L > MAXCH or len(cur) >= MAXSEG):
            batches.append(cur); cur, n = [], 0
        cur.append(s); n += L
    if cur: batches.append(cur)
    return batches

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--langs", default="en,ru,es")
    ap.add_argument("--levels", default="easy,medium,hard")
    a = ap.parse_args()
    langs = [l for l in a.langs.split(",") if l]
    levels = [l for l in a.levels.split(",") if l]

    d = json.load(open(NEWS, encoding="utf-8"))
    keep_from = (datetime.date.today() - datetime.timedelta(days=a.days - 1)).isoformat()
    try:
        g_retry("בדיקה", "en")
    except Exception as e:
        print(f"שירות התרגום אינו נגיש ({type(e).__name__}: {e}) — לא שונה דבר."); return 3

    failed_total = 0
    for lang in langs:
        # אוספים את כל מה שחסר בשפה הזו
        segs, where, nid = [], {}, 0
        for it in d["items"]:
            if it.get("date", "") < keep_from:
                it.pop("tr", None); continue
            cur = it.setdefault("tr", {}).setdefault(lang, {})
            # תיקון תרגומים שנשמרו בעבר ולא תורגמו באמת (נשארו בעברית) או שהכילו "Nemko"
            for k in ["title", *levels]:
                if cur.get(k) and heb_leak(it.get(k, ""), cur[k]): cur.pop(k)
            if cur.get("questions") and any("נמקו" in q for q in it.get("questions", [])): cur.pop("questions")
            for k in ["title", *levels]:
                if it.get(k) and not cur.get(k):
                    segs.append((nid, it[k])); where[nid] = (it, k, None); nid += 1
            if it.get("questions") and not cur.get("questions"):
                for qi, q in enumerate(it["questions"]):
                    segs.append((nid, q)); where[nid] = (it, "questions", qi); nid += 1
        print(f"[{lang}] קטעים לתרגום: {len(segs)}")
        qtmp = {}
        for batch in make_batches(segs):
            try:
                res = translate_batch(batch, lang)
            except Exception as e:
                failed_total += len(batch); print(f"  נכשלה קבוצה: {type(e).__name__}: {e}"); continue
            for i, txt in res.items():
                it, k, qi = where[i]
                if k == "questions":
                    qtmp.setdefault(id(it), {})[qi] = txt
                else:
                    it["tr"][lang][k] = txt
            json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for it in d["items"]:
            q = qtmp.get(id(it))
            if q and it.get("questions") and len(q) == len(it["questions"]):
                it["tr"][lang]["questions"] = [q[i] for i in range(len(it["questions"]))]
            elif q:
                failed_total += 1
        # ניקוי שפות שאינן ברשימה ותרגומים ריקים
        for it in d["items"]:
            tr = it.get("tr")
            if tr is None: continue
            for l in list(tr):
                if l not in langs or not tr[l]: tr.pop(l)
            if not tr: it.pop("tr", None)
        json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"נכשלו: {failed_total}")
    return 0 if failed_total == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
