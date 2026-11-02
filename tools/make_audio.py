#!/usr/bin/env python3
"""הפקת קובצי שמע (קול קריין נוירוני, עברית) לידיעות של "עיתון גן דוד".

שימוש:  python3 tools/make_audio.py [--days 7] [--levels easy,medium,hard,expert]

- קורא את data/news.json, מפיק לכל ידיעה מ-N הימים האחרונים קובץ MP3 לכל רמה
  (audio/<id>-<level>.mp3) אם עדיין אינו קיים, ומוחק קבצים של ידיעות ישנות יותר.
- מעדכן בכל ידיעה שדה "audio": רשימת הרמות שיש להן קובץ.
- דורש: pip install edge-tts ; ffmpeg (לדחיסה). אם ffmpeg חסר — נשמר הקובץ המקורי.
- השירות: Microsoft Edge TTS (speech.platform.bing.com). אם אינו נגיש — הסקריפט מדווח ויוצא בלי לשנות דבר.
"""
import asyncio, json, os, sys, glob, datetime, shutil, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS = os.path.join(ROOT, "data", "news.json")
AUDIO = os.path.join(ROOT, "audio")
VOICE = "he-IL-HilaNeural"
LEVELS = ["easy", "medium", "hard", "expert"]
DEFAULT_LEVELS = ["easy", "medium", "hard"]

def tts_text(item, level):
    body = (item.get(level) or "").replace("\n", ". ").replace("..", ".")
    return f"{item.get('title','')}. {body}"

async def synth(text, out_path, proxy):
    import edge_tts
    tmp = out_path + ".tmp.mp3"
    comm = edge_tts.Communicate(text, VOICE, rate="-5%", proxy=proxy)
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
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    levels = [l for l in a.levels.split(",") if l in LEVELS]
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

    items = [it for it in d["items"] if it.get("date", "") >= keep_from]
    todo = []
    for it in items:
        for lv in levels:
            path = os.path.join(AUDIO, f"{it['id']}-{lv}.mp3")
            if not os.path.exists(path) and it.get(lv):
                todo.append((it, lv, path))
    print(f"ידיעות בטווח: {len(items)} | קבצים להפקה: {len(todo)}")

    sem = asyncio.Semaphore(a.concurrency)
    ok = fail = 0
    async def one(it, lv, path):
        nonlocal ok, fail
        async with sem:
            for attempt in range(3):
                try:
                    await synth(tts_text(it, lv), path, proxy); ok += 1; return
                except Exception as e:
                    err = e; await asyncio.sleep(2 + attempt * 3)
            fail += 1; print(f"נכשל: {os.path.basename(path)} — {type(err).__name__}: {err}")
    await asyncio.gather(*(one(*t) for t in todo))

    # מחיקת קבצים ישנים / יתומים
    keep_ids = {it["id"] for it in items}
    removed = 0
    for f in glob.glob(os.path.join(AUDIO, "*.mp3")):
        base = os.path.basename(f)[:-4]
        iid = base.rsplit("-", 1)[0]
        if iid not in keep_ids:
            os.remove(f); removed += 1

    # עדכון שדה audio
    for it in d["items"]:
        have = [lv for lv in LEVELS if os.path.exists(os.path.join(AUDIO, f"{it['id']}-{lv}.mp3"))]
        if have: it["audio"] = have
        else: it.pop("audio", None)
    json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total = sum(os.path.getsize(f) for f in glob.glob(os.path.join(AUDIO, "*.mp3")))
    print(f"הופקו: {ok} | נכשלו: {fail} | נמחקו ישנים: {removed} | גודל תיקיית audio: {total/1e6:.1f}MB")
    return 0 if fail == 0 else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
