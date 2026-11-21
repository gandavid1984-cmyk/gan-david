#!/usr/bin/env python3
"""הפקת קובצי שמע (קול קריין נוירוני, עברית) לידיעות של "עיתון גן דוד".

שימוש:  python3 tools/make_audio.py [--days 7] [--levels easy,medium,hard,expert]

- קורא את data/news.json, מפיק לכל ידיעה מ-N הימים האחרונים קובץ MP3 לכל רמה
  (audio/<id>-<level>.mp3) אם עדיין אינו קיים, ומוחק קבצים של ידיעות ישנות יותר.
- מעדכן בכל ידיעה שדה "audio": רשימת הרמות שיש להן קובץ בעברית.
- --langs he,en,ru,es: לכל שפה מלבד עברית מפיק שמע מהתרגום השמור (tr) לקובץ audio/<id>-<level>-<lang>.mp3 ומעדכן
  שדה "audioTr": {"en": [רמות], ...}. הקול לכל שפה ב-VOICES; קול שאינו קיים בשירות — מדלגים על השפה ומדפיסים אזהרה.
- --budget-min: תקרת זמן; אחריה לא מתחילים קבצים חדשים (מה שנשאר יופק בריצה הבאה). הכי חדש קודם.
- מילון הגייה לשמות: tools/tts_lexicon.json (מילה -> צורה מנוקדת); מוחלים לפני ההפקה.
- דורש: pip install edge-tts ; ffmpeg (לדחיסה). אם ffmpeg חסר — נשמר הקובץ המקורי.
- השירות: Microsoft Edge TTS (speech.platform.bing.com). אם אינו נגיש — הסקריפט מדווח ויוצא בלי לשנות דבר.
"""
import asyncio, json, os, re, sys, time, glob, datetime, shutil, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS = os.path.join(ROOT, "data", "news.json")
AUDIO = os.path.join(ROOT, "audio")
VOICES = {"he": "he-IL-HilaNeural", "en": "en-US-JennyNeural", "ru": "ru-RU-SvetlanaNeural", "es": "es-ES-ElviraNeural"}
VOICE = VOICES["he"]
NAME_RE = re.compile(r"^(?P<id>.+)-(?P<lv>easy|medium|hard|expert)(?:-(?P<lang>en|ru|es))?$")
LEVELS = ["easy", "medium", "hard", "expert"]
DEFAULT_LEVELS = ["easy", "medium", "hard"]

LEXICON_PATH = os.path.join(ROOT, "tools", "tts_lexicon.json")
def load_lexicon():
    """מילון הגייה: מילה/שם -> צורה מנוקדת. נטען פעם אחת; החלפה מהארוך לקצר."""
    try:
        lex = json.load(open(LEXICON_PATH, encoding="utf-8"))
        return sorted(((k, v) for k, v in lex.items() if k and v), key=lambda kv: -len(kv[0]))
    except Exception:
        return []
LEXICON = load_lexicon()

# \u05d0\u05d5\u05ea\u05d9\u05d5\u05ea \u05e9\u05d9\u05de\u05d5\u05e9 (\u05de\u05e9"\u05d4 \u05d5\u05db\u05dc"\u05d1) \u05e9\u05d9\u05db\u05d5\u05dc\u05d5\u05ea \u05dc\u05d4\u05d5\u05e4\u05d9\u05e2 \u05dc\u05e4\u05e0\u05d9 \u05de\u05d9\u05dc\u05d4 \u05de\u05d4\u05de\u05d9\u05dc\u05d5\u05df; \u05de\u05e0\u05d5\u05e7\u05d3\u05d5\u05ea \u05d1\u05e0\u05d9\u05e7\u05d5\u05d3 \u05e8\u05d2\u05d9\u05dc
PREFIXES = {"": "", "\u05d5": "\u05d5\u05b0", "\u05d1": "\u05d1\u05b0\u05bc", "\u05dc": "\u05dc\u05b0", "\u05de": "\u05de\u05b4", "\u05d4": "\u05d4\u05b7", "\u05e9": "\u05e9\u05b6\u05c1", "\u05db": "\u05db\u05b0\u05bc",
            "\u05d5\u05d1": "\u05d5\u05bc\u05d1\u05b0", "\u05d5\u05dc": "\u05d5\u05bc\u05dc\u05b0", "\u05d5\u05de": "\u05d5\u05bc\u05de\u05b4", "\u05d5\u05d4": "\u05d5\u05b0\u05d4\u05b7", "\u05d5\u05e9": "\u05d5\u05b0\u05e9\u05b6\u05c1", "\u05d5\u05db": "\u05d5\u05bc\u05db\u05b0",
            "\u05db\u05e9": "\u05db\u05b0\u05bc\u05e9\u05b6\u05c1", "\u05e9\u05d1": "\u05e9\u05b6\u05c1\u05d1\u05b0\u05bc", "\u05e9\u05dc": "\u05e9\u05b6\u05c1\u05dc\u05b0\u05bc", "\u05e9\u05d4": "\u05e9\u05b6\u05c1\u05d4\u05b7", "\u05e9\u05de": "\u05e9\u05b6\u05c1\u05de\u05b4\u05bc", "\u05de\u05d4": "\u05de\u05b5\u05d4\u05b7",
            "\u05d1\u05d4": "\u05d1\u05b7\u05bc", "\u05dc\u05d4": "\u05dc\u05b7", "\u05db\u05d4": "\u05db\u05b7\u05bc", "\u05d5\u05d1\u05d4": "\u05d5\u05bc\u05d1\u05b7", "\u05d5\u05dc\u05d4": "\u05d5\u05bc\u05dc\u05b7", "\u05d5\u05de\u05d4": "\u05d5\u05bc\u05de\u05b5\u05d4\u05b7", "\u05d5\u05db\u05e9": "\u05d5\u05bc\u05db\u05b0\u05e9\u05b6\u05c1"}
_PREFIX_RE = "(?:" + "|".join(sorted((p for p in PREFIXES if p), key=len, reverse=True)) + ")?"

def apply_lexicon(text):
    """\u05de\u05d7\u05dc\u05d9\u05e3 \u05db\u05dc \u05de\u05d9\u05dc\u05d4 \u05de\u05d4\u05de\u05d9\u05dc\u05d5\u05df \u05d1\u05e6\u05d5\u05e8\u05ea\u05d4 \u05d4\u05de\u05e0\u05d5\u05e7\u05d3\u05ea, \u05d2\u05dd \u05db\u05e9\u05d9\u05e9 \u05dc\u05e4\u05e0\u05d9\u05d4 \u05d0\u05d5\u05ea \u05e9\u05d9\u05de\u05d5\u05e9 (\u05d1\u05d8\u05de\u05e4\u05e8\u05d8\u05d5\u05e8\u05d5\u05ea, \u05d5\u05d4\u05d0\u05d5\u05e0\u05d9\u05d1\u05e8\u05e1\u05d9\u05d8\u05d4).
    \u05e2\u05e8\u05da \u05e9\u05db\u05d1\u05e8 \u05db\u05d5\u05dc\u05dc \u05d4' \u05d4\u05d9\u05d3\u05d9\u05e2\u05d4 \u05d1\u05ea\u05d7\u05d9\u05dc\u05ea\u05d5 (\u05dc\u05de\u05e9\u05dc "\u05d4\u05d3\u05d5\u05d3\u05d0\u05d9\u05dd") \u05e0\u05ea\u05e4\u05e1 \u05db\u05de\u05d5 \u05e9\u05d4\u05d5\u05d0; \u05d4\u05d4\u05d7\u05dc\u05e4\u05d4 \u05d4\u05d9\u05d0 \u05e2\u05dc \u05de\u05d9\u05dc\u05d4 \u05e9\u05dc\u05de\u05d4."""
    import re
    for k, v in LEXICON:
        pat = r"(?<![\u05d0-\u05ea])(" + _PREFIX_RE + r")" + re.escape(k) + r"(?![\u05d0-\u05ea])"
        text = re.sub(pat, lambda m, v=v: PREFIXES.get(m.group(1), m.group(1)) + v, text)
    return text

def audio_path(iid, lv, lang):
    return os.path.join(AUDIO, f"{iid}-{lv}.mp3" if lang == "he" else f"{iid}-{lv}-{lang}.mp3")

def tts_text(item, level, lang="he"):
    if lang == "he":
        body = (item.get(level) or "").replace("\n\n", "\n").replace("\n", ". ").replace("..", ".")
        return apply_lexicon(f"{item.get('title','')}. {body}")
    tr = (item.get("tr") or {}).get(lang) or {}
    title, body = tr.get("title") or "", (tr.get(level) or "").replace("\n\n", "\n").replace("\n", ". ").replace("..", ".")
    return f"{title}. {body}" if title and body else ""

async def synth(text, out_path, proxy, voice=VOICE):
    import edge_tts
    tmp = out_path + ".tmp.mp3"
    comm = edge_tts.Communicate(text, voice, rate="-5%", proxy=proxy)
    await comm.save(tmp)
    if os.path.getsize(tmp) < 1000:
        os.remove(tmp); raise RuntimeError("empty audio")
    if shutil.which("ffmpeg"):
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-ac", "1", "-ar", "24000", "-b:a", "24k", out_path])
        if r.returncode == 0 and os.path.getsize(out_path) > 1000:
            os.remove(tmp); return
    os.replace(tmp, out_path)

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--levels", default=",".join(DEFAULT_LEVELS))
    ap.add_argument("--langs", default="he")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--budget-min", type=float, default=60.0)
    a = ap.parse_args()
    levels = [l for l in a.levels.split(",") if l in LEVELS]
    langs = [l for l in a.langs.split(",") if l in VOICES]
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        import edge_tts  # noqa
    except ImportError:
        print("edge-tts לא מותקן (pip install edge-tts)"); return 2

    d = json.load(open(NEWS, encoding="utf-8"))
    today = datetime.date.today()
    keep_from = (today - datetime.timedelta(days=a.days - 1)).isoformat()
    os.makedirs(AUDIO, exist_ok=True)

    # בדיקת נגישות השירות
    try:
        await synth("בדיקה.", os.path.join(AUDIO, "_check.mp3"), proxy)
        os.remove(os.path.join(AUDIO, "_check.mp3"))
    except Exception as e:
        print(f"שירות הקול אינו נגיש ({type(e).__name__}: {e}) — לא נוצרו קבצים."); return 3

    # קולות לפי שפה: מוודאים שהקול קיים בשירות
    try:
        have_voices = {v["ShortName"] for v in await edge_tts.list_voices()}
    except Exception as e:
        print(f"לא הצלחתי לקבל את רשימת הקולות ({type(e).__name__}: {e}) — ממשיך בלי בדיקה"); have_voices = None
    for l in list(langs):
        if have_voices is not None and VOICES[l] not in have_voices:
            print(f"::warning::הקול {VOICES[l]} ({l}) אינו קיים בשירות — מדלג על השפה"); langs.remove(l)
    print("שפות להפקה:", ", ".join(f"{l} ({VOICES[l]})" for l in langs))

    items = [it for it in d["items"] if it.get("date", "") >= keep_from]
    todo = []
    for it in sorted(items, key=lambda x: str(x.get("date", "")), reverse=True):     # הכי חדש קודם
        for lang in langs:
            for lv in levels:
                path = audio_path(it["id"], lv, lang)
                if os.path.exists(path): continue
                text = tts_text(it, lv, lang)
                if text.strip(". "): todo.append((it, lv, lang, path, text))
    print(f"ידיעות בטווח: {len(items)} | קבצים להפקה: {len(todo)}", flush=True)

    deadline = time.time() + a.budget_min * 60
    sem = asyncio.Semaphore(a.concurrency)
    ok = fail = skipped = 0
    async def one(it, lv, lang, path, text):
        nonlocal ok, fail, skipped
        async with sem:
            if time.time() > deadline: skipped += 1; return
            err = None
            for attempt in range(3):
                try:
                    await synth(text, path, proxy, VOICES[lang]); ok += 1
                    if ok % 50 == 0: print(f"  הופקו {ok} קבצים...", flush=True)
                    return
                except Exception as e:
                    err = e; await asyncio.sleep(2 + attempt * 3)
            fail += 1; print(f"נכשל: {os.path.basename(path)} — {type(err).__name__}: {err}")
    await asyncio.gather(*(one(*t) for t in todo))
    if skipped:
        print(f"::warning::נגמרה תקרת הזמן ({a.budget_min:g} דקות): {skipped} קבצים נשארו — יופקו בריצה הבאה (הכי חדשים כבר הופקו)")

    # מחיקת קבצים ישנים / יתומים
    keep_ids = {it["id"] for it in items}
    removed = 0
    for f in glob.glob(os.path.join(AUDIO, "*.mp3")):
        m = NAME_RE.match(os.path.basename(f)[:-4])
        if not m or m.group("id") not in keep_ids:
            os.remove(f); removed += 1

    # עדכון שדות audio (עברית) ו-audioTr (שפות אחרות)
    for it in d["items"]:
        have = [lv for lv in LEVELS if os.path.exists(audio_path(it["id"], lv, "he"))]
        if have: it["audio"] = have
        else: it.pop("audio", None)
        atr = {l: [lv for lv in LEVELS if os.path.exists(audio_path(it["id"], lv, l))] for l in ("en", "ru", "es")}
        atr = {l: v for l, v in atr.items() if v}
        if atr: it["audioTr"] = atr
        else: it.pop("audioTr", None)
    json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total = sum(os.path.getsize(f) for f in glob.glob(os.path.join(AUDIO, "*.mp3")))
    print(f"הופקו: {ok} | נכשלו: {fail} | נותרו לריצה הבאה: {skipped} | נמחקו ישנים: {removed} | גודל תיקיית audio: {total/1e6:.1f}MB")
    return 0 if fail == 0 else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
