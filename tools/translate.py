#!/usr/bin/env python3
"""תרגום מוכן מראש לידיעות של "עיתון גן דוד" — ל-en/ru/es.

שימוש:  python3 tools/translate.py [--days 30] [--langs en,ru,es] [--levels easy,medium,hard]

- קורא את data/news.json, ולכל ידיעה מ-N הימים האחרונים שחסר לה תרגום לשפה — מתרגם
  כותרת, הרמות המבוקשות ושלוש השאלות (וגם שאלות לפי רמה), ושומר בידיעה:
  "tr": {"en": {"title", "easy", "medium", "hard", "questions", "qlevels"}, ...}.
- מה שכבר מתורגם לא נשלח שוב.
- מנוע ראשי: Gemini API (הרמה החינמית), כשקיים הסוד GEMINI_API_KEY. המודל קבוע (GEMINI_MODELS, ברירת מחדל
  gemini-3.8-flash ואחריו gemini-3.5-flash-lite) — לא "latest", כדי שלא יתחלף בלי שנדע. הבקשה כוללת רשימת שמות
  מ-tools/glossary.json (רק מונחים שמופיעים בקבוצה). כל תרגום נבדק: לא חזר בעברית, כל המספרים מהמקור נשמרו,
  כל המפתחות חזרו. תרגום שנכשל בבדיקה — הקבוצה מפוצלת ומנוסה שוב.
- גיבוי: שירות התרגום החינמי של Google (לא רשמי; עלול להיחסם). משמש רק לקטע ש-Gemini לא הצליח בו, או לכל הריצה
  אם אין מפתח. בסוף הריצה מודפס כמה קטעים תורגמו בכל מנוע, ואם היה גיבוי של Google — אזהרה ב-GitHub.
- אם נשאר משהו שלא תורגם — הסקריפט מסיים בקוד שגיאה, וההרצה ב-GitHub מסומנת ככשלון (ולא נבלעת בשקט).
"""
import json, os, re, sys, time, argparse, datetime, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS = os.path.join(ROOT, "data", "news.json")
URL_POST = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=iw&tl={lang}&dt=t"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


MAXCH = 3500      # תווים מקסימליים בבקשה אחת
MAXSEG = 40       # קטעים מקסימליים בבקשה אחת
PAUSE = 3.0       # המתנה בין בקשות (שניות)
WAITS = [10, 40, 120, 240]   # המתנה בין ניסיונות חוזרים
DEADLINE = [float("inf")]   # תקרת זמן גלובלית (נקבעת ב-main) — מונעת המתנות ארוכות אחרי שנגמר הזמן
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

GOOG_FAILS = [0]
def g_retry(text, lang):
    if GOOG_FAILS[0] >= 2:
        raise RuntimeError("Google חסום (429) — לא מנסה שוב בריצה הזו")
    err = None
    for w in [0] + WAITS:
        if time.time() > DEADLINE[0]: raise TimeoutError("נגמרה תקרת הזמן")
        if w: time.sleep(w)
        try:
            out = g_post(text, lang); time.sleep(PAUSE); GOOG_FAILS[0] = 0; return out
        except Exception as e:
            err = e
    GOOG_FAILS[0] += 1
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

def google_batch(segs, lang):
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
    res = google_batch(segs[:mid], lang)
    res.update(google_batch(segs[mid:], lang))
    return res

# ───────────────────────── Gemini (מנוע ראשי) ─────────────────────────
KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODELS = [m.strip() for m in os.environ.get("GEMINI_MODELS", "gemini-3.8-flash,gemini-3.5-flash-lite").split(",") if m.strip()]
GURL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
GPAUSE = 6.0                 # המתנה בין בקשות (הרמה החינמית מוגבלת בקצב)
GWAITS = [20, 60, 120]       # המתנה בין ניסיונות חוזרים בשגיאת עומס (429/5xx)
LANGN = {"en": "English", "ru": "Russian", "es": "Spanish"}
STYLE = {
    "en": "",
    "ru": "Questions to the readers address a group: use the polite plural «вы» forms.",
    "es": "Questions to the readers address a group: use «ustedes» forms (for example «Cuéntennos», «Expliquen su respuesta»).",
}
STATS = {"gemini": 0, "google": 0}
GEM_DEAD = [False]           # מפתח לא תקין/אין הרשאה/עומס מתמשך — לא ממשיכים לנסות
MODEL_BAD = {}               # מודל -> כמה פעמים נכשל אחרי כל הניסיונות החוזרים; אחרי 2 מדלגים עליו (אם יש מודל אחר)
GEM_FAILS = [0]              # בקשות רצופות שנכשלו אחרי כל הניסיונות החוזרים
MAX_FAILS = 3

class GemFatal(Exception):
    pass

def load_glossary():
    try:
        return json.load(open(os.path.join(ROOT, "tools", "glossary.json"), encoding="utf-8"))
    except Exception:
        return {}
GLOSSARY = load_glossary()

def glossary_for(segs, lang):
    text = " ".join(t for _, t in segs)
    return {k: v[lang] for k, v in GLOSSARY.items() if not k.startswith("_") and k in text and v.get(lang)}

def gem_request(model, prompt):
    gc = {"temperature": 0.2, "responseMimeType": "application/json", "maxOutputTokens": 8192}
    if "2.5-flash" in model and "lite" not in model:
        gc["thinkingConfig"] = {"thinkingBudget": 0}      # בלי "חשיבה" — מקצר ומוזיל
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gc}).encode()
    last = None
    for w in [0] + GWAITS:
        if time.time() > DEADLINE[0]: raise TimeoutError("נגמרה תקרת הזמן")
        if w: time.sleep(w)
        try:
            req = urllib.request.Request(GURL.format(model), data=body,
                                         headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                j = json.loads(r.read().decode("utf-8"))
            out = j["candidates"][0]["content"]["parts"][0]["text"]
            time.sleep(GPAUSE)
            GEM_FAILS[0] = 0; MODEL_BAD[model] = 0
            return out
        except urllib.error.HTTPError as e:
            msg = e.read()[:200]
            if e.code in (400, 401, 403):
                raise GemFatal(f"HTTP {e.code}: {msg!r}")
            if e.code not in (429, 500, 502, 503, 504):
                GEM_FAILS[0] += 1
                if GEM_FAILS[0] >= MAX_FAILS * len(MODELS):
                    raise GemFatal(f"HTTP {e.code} חוזר שוב ושוב: {msg!r} — מפסיק להשתמש ב-Gemini בריצה הזו")
                raise RuntimeError(f"HTTP {e.code}: {msg!r}")
            print(f"  Gemini {model}: HTTP {e.code} (ניסיון חוזר)")
            last = e
        except Exception as e:
            print(f"  Gemini {model}: {type(e).__name__}: {e} (ניסיון חוזר)")
            last = e
    GEM_FAILS[0] += 1; MODEL_BAD[model] = MODEL_BAD.get(model, 0) + 1
    if GEM_FAILS[0] >= MAX_FAILS:
        raise GemFatal(f"{MAX_FAILS} בקשות רצופות נכשלו (עומס/מכסה) — מפסיק להשתמש ב-Gemini בריצה הזו")
    raise last

NUM_RE = re.compile(r"\d[\d,.]*")
def nums(text):
    return [re.sub(r"[,.]", "", n) for n in NUM_RE.findall(text)]

def gem_validate(raw, segs):
    """מחזיר {id: תרגום} או None אם משהו לא תקין."""
    try:
        d = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
    except Exception:
        print("  Gemini: תשובה שאינה JSON — מפצל"); return None
    if not isinstance(d, dict): print("  Gemini: מבנה לא צפוי — מפצל"); return None
    res = {}
    for i, t in segs:
        out = d.get(str(i))
        if not isinstance(out, str) or (t.strip() and not out.strip()):
            print(f"  Gemini: חסר תרגום לקטע {i} — מפצל"); return None
        if heb_leak(t, out):
            print(f"  Gemini: קטע {i} חזר בעברית — מפצל"); return None
        out_nums = nums(out)
        if any(n not in out_nums for n in nums(t)):
            print(f"  Gemini: מספר מהמקור חסר בקטע {i} — מפצל"); return None
        res[i] = out.strip()
    return res

def gem_try(segs, lang):
    """מנסה את המודלים לפי הסדר (רק בשגיאת בקשה עוברים למודל הבא). מחזיר dict או None."""
    gl = glossary_for(segs, lang)
    gtxt = ("\nGlossary (Hebrew = %s) — use exactly these forms:\n" % LANGN[lang] +
            "\n".join(f"- {k} = {v}" for k, v in gl.items())) if gl else ""
    prompt = (
        f"You translate short Hebrew texts from a simplified news site for elderly readers in Israeli nursing homes into {LANGN[lang]}.\n"
        "Rules:\n"
        "- Simple, warm, natural language, at the same register as the source.\n"
        "- Keep every fact, number, date and name exactly as in the source. Do not add, omit, explain or soften anything.\n"
        f"- Use the standard {LANGN[lang]} spelling of Israeli names, parties, places, teams and institutions, and the same spelling for the same name everywhere.\n"
        "- Translate everything fully; never leave Hebrew words in the output.\n"
        "- Write every number as digits exactly as in the source (scores, ages, years, times, percentages); never spell a number out and never drop one.\n"
        + (STYLE[lang] + "\n" if STYLE[lang] else "")
        + gtxt +
        "\nReturn ONLY a JSON object with exactly the same keys as the input; each value is the translation of the value with that key.\n\n"
        "Input:\n" + json.dumps({str(i): t for i, t in segs}, ensure_ascii=False))
    for model in MODELS:
        if MODEL_BAD.get(model, 0) >= 2 and len(MODELS) > 1:
            continue
        try:
            raw = gem_request(model, prompt)
        except GemFatal:
            raise
        except Exception as e:
            print(f"  Gemini {model} נכשל ({type(e).__name__}: {str(e)[:300]}) — עובר למודל הבא")
            continue
        return gem_validate(raw, segs)
    return None

def translate_batch(segs, lang):
    """Gemini; קבוצה שנכשלה בבדיקה מפוצלת; קטע בודד שנכשל, או Gemini לא זמין — Google."""
    if KEY and not GEM_DEAD[0]:
        try:
            res = gem_try(segs, lang)
        except GemFatal as e:
            GEM_DEAD[0] = True
            print(f"  ::warning::Gemini לא זמין ({e}) — ממשיך עם Google")
            res = None
        if res is not None:
            STATS["gemini"] += len(segs); return res
        if len(segs) > 1 and not GEM_DEAD[0]:
            mid = len(segs) // 2
            out = translate_batch(segs[:mid], lang)
            out.update(translate_batch(segs[mid:], lang))
            return out
    try:
        res = google_batch(segs, lang)
    except Exception as e:
        print(f"  לא תורגמו {len(segs)} קטעים (Gemini וגם Google נכשלו): {type(e).__name__}: {e}")
        return {}                      # רק הקטעים האלה נשארים לריצה הבאה; מה שתורגם קודם בקבוצה נשמר
    STATS["google"] += len(segs)
    return res

def gem_list():
    """רשימת המודלים שהמפתח רואה (שם בלבד). הרשימה לא מבטיחה שהמודל עובד — לכן בודקים בפועל."""
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.loads(r.read().decode("utf-8"))
    return [m["name"].split("/")[-1] for m in j.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]

STABLE = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash(-lite)?$")   # יציבים בלבד: בלי preview/image/tts/latest

def gem_probe(model):
    """בקשה אמיתית וקטנה. מחזיר 'ok' | 'busy' (503/429 — קיים אבל עמוס) | 'dead' (404/לא זמין)."""
    body = json.dumps({"contents": [{"parts": [{"text": 'Translate to English, return JSON {"t": "..."}: שלום'}]}],
                       "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json", "maxOutputTokens": 100}}).encode()
    try:
        req = urllib.request.Request(GURL.format(model), data=body, headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            json.loads(r.read().decode("utf-8"))
        return "ok"
    except urllib.error.HTTPError as e:
        if e.code in (429, 500, 502, 503, 504): return "busy"
        print(f"  בדיקת {model}: HTTP {e.code} — {e.read()[:250]!r}")
        return "dead"
    except Exception as e:
        print(f"  בדיקת {model}: {type(e).__name__}: {e}")
        return "busy"

def choose_models(pinned, want=2):
    """מודלים קבועים שעוברים בדיקה בפועל; אם פחות מ-want — משלימים מהרשימה של Google (יציבים בלבד, החדש ראשון)
    ומדפיסים אזהרה. כך מודל שהוסר לא עוצר את התרגום, ואנחנו יודעים שהמודל התחלף."""
    good, status = [], {}
    for m in pinned:
        st = gem_probe(m); time.sleep(2)
        print(f"  מודל {m}: {st}")
        status[m] = st
        if st != "dead": good.append(m)
    good.sort(key=lambda m: status[m] != "ok")      # מודל תקין לפני מודל עמוס (503) — זמינות לפני העדפה
    if len(good) >= want: return good
    try:
        names = gem_list()
    except Exception as e:
        print(f"  לא הצלחתי לקבל את רשימת המודלים ({type(e).__name__}: {e})"); return good
    cands = sorted({n for n in names if STABLE.match(n) and n not in pinned},
                   key=lambda n: (-float(STABLE.match(n).group(1)), bool(STABLE.match(n).group(2))))
    for m in cands:
        if len(good) >= want: break
        st = gem_probe(m); time.sleep(2)
        print(f"  מודל חלופי {m}: {st}")
        status[m] = st
        if st != "dead": good.append(m)
    good.sort(key=lambda m: status[m] != "ok")
    if sorted(good) != sorted(pinned):
        print(f"::warning::המודלים הקבועים ({', '.join(pinned)}) לא כולם זמינים — משתמש ב: {', '.join(good) or 'אין'}. כדאי לעדכן את GEMINI_MODELS ולבדוק את איכות התרגום.")
    return good

def gemini_check():
    """בדיקה מהירה: בקשת תרגום קטנה לכל מודל; מדפיסה קוד שגיאה והודעה (בלי המפתח)."""
    if not KEY:
        print("אין GEMINI_API_KEY"); return 2
    bad = 0
    for model in MODELS:
        body = json.dumps({"contents": [{"parts": [{"text": 'Translate to English, return JSON {"t": "..."}: שלום, מה שלומכם היום?'}]}],
                           "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json", "maxOutputTokens": 200}}).encode()
        try:
            req = urllib.request.Request(GURL.format(model), data=body, headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read().decode("utf-8"))
            print(f"{model}: OK — {j['candidates'][0]['content']['parts'][0]['text'][:120]!r}")
        except urllib.error.HTTPError as e:
            bad += 1; print(f"{model}: HTTP {e.code} — {e.read()[:500]!r}")
        except Exception as e:
            bad += 1; print(f"{model}: {type(e).__name__}: {e}")
        time.sleep(3)
    print("בחירת מודלים בפועל:", choose_models(list(MODELS)))
    return 1 if bad else 0

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
    ap.add_argument("--budget-min", type=float, default=float(os.environ.get("TRANSLATE_BUDGET_MIN", "50")),
                    help="תקרת זמן בדקות: אחריה עוצרים, שומרים מה שתורגם ומסיימים בקוד שגיאה (כדי שה-commit ירוץ)")
    ap.add_argument("--check", action="store_true", help="בדיקת חיבור ל-Gemini בלבד (בקשה קטנה לכל מודל), בלי לגעת בידיעות")
    a = ap.parse_args()
    if a.check:
        return gemini_check()
    langs = [l for l in a.langs.split(",") if l]
    levels = [l for l in a.levels.split(",") if l]

    d = json.load(open(NEWS, encoding="utf-8"))
    keep_from = (datetime.date.today() - datetime.timedelta(days=a.days - 1)).isoformat()
    if not KEY:
        print("אין GEMINI_API_KEY — מתרגם עם Google בלבד.")
        try:
            g_retry("בדיקה", "en")
        except Exception as e:
            print(f"שירות התרגום אינו נגיש ({type(e).__name__}: {e}) — לא שונה דבר."); return 3
    else:
        MODELS[:] = choose_models(MODELS)
        if not MODELS:
            GEM_DEAD[0] = True
            print("::warning::אין מודל Gemini זמין — מתרגם עם Google בלבד")
        else:
            print("מנוע ראשי: Gemini, מודלים:", ", ".join(MODELS))

    failed_total = 0
    deadline = time.time() + a.budget_min * 60
    DEADLINE[0] = deadline
    stopped = False
    for lang in langs:
        if stopped: break
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
            ql = it.get("qlevels") or {}
            for lv in levels:
                if ql.get(lv) and not (cur.get("qlevels") or {}).get(lv):
                    for qi, q in enumerate(ql[lv]):
                        segs.append((nid, q)); where[nid] = (it, "qlevels:" + lv, qi); nid += 1
        print(f"[{lang}] קטעים לתרגום: {len(segs)}")
        qtmp = {}
        batches = make_batches(segs)
        for bn, batch in enumerate(batches, 1):
            if time.time() > deadline:
                stopped = True
                failed_total += sum(len(b) for b in batches[bn - 1:])
                print(f"  ::warning::נגמרה תקרת הזמן ({a.budget_min:g} דקות) — עוצר ושומר מה שתורגם; השאר ייתורגם בריצה הבאה")
                break
            print(f"  [{lang}] קבוצה {bn}/{len(batches)} ({len(batch)} קטעים) · {int(time.time() - deadline + a.budget_min * 60)} שנ' מתחילת הריצה", flush=True)
            try:
                res = translate_batch(batch, lang)
            except Exception as e:
                failed_total += len(batch); print(f"  נכשלה קבוצה: {type(e).__name__}: {e}"); continue
            failed_total += len(batch) - len(res)
            for i, txt in res.items():
                it, k, qi = where[i]
                if k == "questions" or k.startswith("qlevels:"):
                    qtmp.setdefault((id(it), k), {})[qi] = txt
                else:
                    it["tr"][lang][k] = txt
            json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for it in d["items"]:
            for k in ["questions"] + ["qlevels:" + lv for lv in levels]:
                q = qtmp.get((id(it), k))
                if not q: continue
                src = it.get("questions") if k == "questions" else (it.get("qlevels") or {}).get(k.split(":")[1])
                if src and len(q) == len(src):
                    lst = [q[i] for i in range(len(src))]
                    if k == "questions": it["tr"][lang]["questions"] = lst
                    else: it["tr"][lang].setdefault("qlevels", {})[k.split(":")[1]] = lst
                else:
                    failed_total += 1
        # ניקוי שפות שאינן ברשימה ותרגומים ריקים
        for it in d["items"]:
            tr = it.get("tr")
            if tr is None: continue
            for l in list(tr):
                if l not in langs or not tr[l]: tr.pop(l)
            if not tr: it.pop("tr", None)
        json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"תורגמו עם Gemini: {STATS['gemini']} קטעים · עם Google (גיבוי): {STATS['google']} קטעים")
    if KEY and STATS["google"]:
        print("::warning::חלק מהקטעים תורגמו עם Google כגיבוי — כדאי לבדוק את הלוג של Gemini")
    print(f"נכשלו: {failed_total}")
    return 0 if failed_total == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
