#!/usr/bin/env python3
"""שמירה של 30 יום בלבד ב-data/news.json (ידיעות ישנות יותר נמחקות). שמע יתום נמחק על ידי make_audio.py."""
import json, os, sys, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS = os.path.join(ROOT, "data", "news.json")
days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
d = json.load(open(NEWS, encoding="utf-8"))
keep_from = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
before = len(d["items"])
d["items"] = sorted([it for it in d["items"] if it.get("date", "") >= keep_from], key=lambda it: (it.get("date", ""), it.get("ts", 0)), reverse=True)
json.dump(d, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"ידיעות: {before} -> {len(d['items'])} (נמחקו {before-len(d['items'])} ישנות מ-{days} יום)")
