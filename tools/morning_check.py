#!/usr/bin/env python3
"""בדיקת בוקר: האם האתר מוכן. מדפיס דוח; יוצא 1 אם יש בעיה (ואז ה-workflow פותח Issue).
בודק את data/news.json שבמאגר, וגם את האתר החי (GitHub Pages) כדי לוודא שהוא מגיש את אותם נתונים."""
import json, os, sys, datetime, urllib.request, zoneinfo

NEWS = "data/news.json"
LANGS = ("en", "ru", "es")
LEVELS = ("easy", "medium", "hard")
SITE = os.environ.get("SITE_URL", "").rstrip("/")

now = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Jerusalem"))
today = now.date()
problems, notes = [], []

def load_local():
    return json.load(open(NEWS, encoding="utf-8"))

def load_live():
    if not SITE: return None
    try:
        req = urllib.request.Request(f"{SITE}/data/news.json?x={int(now.timestamp())}", headers={"Cache-Control": "no-cache"})
        return json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        problems.append(f"האתר החי לא הגיש את data/news.json ({type(e).__name__}: {e})")
        return None

d = load_local()
live = load_live()
if live is not None:
    a, b = {i["id"] for i in d["items"]}, {i["id"] for i in live["items"]}
    if a != b:
        problems.append(f"האתר החי שונה מהמאגר: {len(a-b)} ידיעות במאגר שאינן באתר, {len(b-a)} באתר שאינן במאגר (ייתכן שפרסום עוד רץ)")
    d = live  # בודקים את מה שהמשתמשים באמת רואים

items = d["items"]
# שבת: אין ידיעות חדשות (המשימה הלילית רצה א'-ו'); הבדיקה בוקר היום, לכן בודקים שיש ידיעות של היום, חוץ מבשבת
if today.weekday() != 5:  # 5 = שבת
    todays = [i for i in items if i.get("date") == today.isoformat()]
    if not todays:
        problems.append(f"אין ידיעות של היום ({today.isoformat()}) — המשימה הלילית כנראה לא כתבה או לא דחפה")
    else:
        notes.append(f"ידיעות של היום: {len(todays)}")
else:
    notes.append("שבת — לא נדרשות ידיעות חדשות")

# ידיעות 7 ימים אחרונים: תרגום והקלטות
since = (today - datetime.timedelta(days=6)).isoformat()
recent = [i for i in items if i.get("date", "") >= since]
miss_tr, miss_he, miss_atr = [], [], []
for it in recent:
    tr = it.get("tr") or {}
    for l in LANGS:
        t = tr.get(l) or {}
        if not (t.get("title") and all(t.get(lv) for lv in LEVELS)):
            miss_tr.append(f"{it['id']}:{l}")
    for lv in LEVELS:
        if lv not in (it.get("audio") or []): miss_he.append(f"{it['id']}:{lv}")
    atr = it.get("audioTr") or {}
    for l in LANGS:
        if (tr.get(l) or {}).get("title"):
            for lv in LEVELS:
                if lv not in (atr.get(l) or []): miss_atr.append(f"{it['id']}:{lv}:{l}")
def short(x): return ", ".join(x[:6]) + (f" ועוד {len(x)-6}" if len(x) > 6 else "")
if miss_tr: problems.append(f"חסרים תרגומים ב-{len(miss_tr)} מקרים (ידיעה:שפה): {short(miss_tr)}")
if miss_he: problems.append(f"חסרות הקלטות בעברית ב-{len(miss_he)} מקרים: {short(miss_he)}")
if miss_atr: problems.append(f"חסרות הקלטות בשפות אחרות ב-{len(miss_atr)} מקרים: {short(miss_atr)}")
notes.append(f"ידיעות ב-7 ימים אחרונים: {len(recent)}")

# קבצי שמע שמוצהרים בנתונים וקיימים בפועל (בדיקה בקבצי המאגר)
gone = []
for it in recent:
    for lv in it.get("audio") or []:
        if not os.path.exists(f"audio/{it['id']}-{lv}.mp3"): gone.append(f"{it['id']}-{lv}")
    for l, lvs in (it.get("audioTr") or {}).items():
        for lv in lvs:
            if not os.path.exists(f"audio/{it['id']}-{lv}-{l}.mp3"): gone.append(f"{it['id']}-{lv}-{l}")
if gone: problems.append(f"הנתונים מצהירים על הקלטות שהקובץ שלהן לא קיים: {short(gone)}")

# ריצת העיבוד האחרונה (postprocess) — דרך gh, אם זמין
import subprocess, shutil
if shutil.which("gh") and os.environ.get("GH_TOKEN"):
    try:
        out = subprocess.run(["gh", "run", "list", "--workflow", "postprocess.yml", "--limit", "1", "--json", "conclusion,status,createdAt,url"],
                             capture_output=True, text=True, timeout=60).stdout
        r = json.loads(out)[0]
        age_h = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))).total_seconds() / 3600
        if r["status"] == "completed" and r["conclusion"] not in ("success",):
            problems.append(f"ריצת העיבוד האחרונה נגמרה ב-{r['conclusion']} (לפני {age_h:.0f} שעות): {r['url']}")
        else:
            notes.append(f"ריצת עיבוד אחרונה: {r['status']}/{r['conclusion']} לפני {age_h:.0f} שעות")
    except Exception as e:
        notes.append(f"לא הצלחתי לבדוק את ריצת העיבוד האחרונה ({type(e).__name__})")

print(f"בדיקת בוקר — {now:%Y-%m-%d %H:%M} (ישראל)")
for n in notes: print("  •", n)
if problems:
    print("בעיות:")
    for p in problems: print("  ✗", p)
    open("morning_report.md", "w", encoding="utf-8").write("\n".join(f"- {p}" for p in problems) + "\n\n" + "\n".join(f"- {n}" for n in notes) + "\n")
    sys.exit(1)
print("הכול תקין ✓")
