#!/usr/bin/env python3
"""
SocialSoundSystem — Walk-Up Deploy Script (updated)
====================================================
Fetches mlb.json from GitHub Pages, injects into index.html, pushes to Vercel.

Run: python3 deploy.py
"""

import re, sys, json, shutil, subprocess, requests
from pathlib import Path
from datetime import date

HERE    = Path(__file__).parent.resolve()
HTML_IN = HERE / "index.html"

# ── Data source: your GitHub Pages endpoint ───────────────────────────────────
DATA_URL = "https://socialsoundsystem.github.io/sss-walkup-data/mlb.json"

print("=" * 54)
print("  🎵 SocialSoundSystem — Walk-Up Deploy")
print(f"  📁 {HERE}")
print("=" * 54)

# ── Preflight ─────────────────────────────────────────────────────────────────
if not HTML_IN.exists():
    print("  ✗ MISSING: index.html")
    sys.exit(1)
print("  ✓ index.html")

# ── Fetch fresh data from GitHub Pages ───────────────────────────────────────
print(f"\n  Fetching data from GitHub Pages...")
try:
    r = requests.get(DATA_URL, timeout=30)
    r.raise_for_status()
    data = r.json()
except Exception as e:
    print(f"  ✗ Failed to fetch {DATA_URL}")
    print(f"    {e}")
    print("\n  💡 Make sure sss-walkup-data GitHub Pages is live and the")
    print("     scraper has run at least once (Actions → Run workflow).")
    sys.exit(1)

players   = data.get("players", [])
data_date = data.get("dataAsOf", "unknown")
print(f"  ✓ {len(players)} entries · data as of {data_date}")

# ── Build const P=[...] ───────────────────────────────────────────────────────
def esc(s):
    return str(s or "").replace("\\", "\\\\").replace('"', '\\"')

lines = []
for p in players:
    id_val = f'"{esc(p["id"])}"' if p.get("id") else "null"
    lines.append(
        f'{{n:"{esc(p["n"])}",t:"{esc(p["t"])}",s:"{esc(p["s"])}",'
        f'a:"{esc(p["a"])}",p:"{esc(p["p"])}",id:{id_val},'
        f'artworkUrl:"{esc(p.get("artworkUrl",""))}",spotifyUrl:"{esc(p.get("spotifyUrl",""))}",'
        f'src:"{esc(p.get("src","mlb.com"))}",upd:"{esc(p.get("upd",""))}"'
        f'}}'
    )

js_block = f"const P=[\n  " + ",\n  ".join(lines) + "\n];"

# ── Inject into index.html ────────────────────────────────────────────────────
html = HTML_IN.read_text(encoding="utf-8")

if "const P=[" not in html:
    print("  ✗ 'const P=[' not found in index.html — check the script block")
    sys.exit(1)

injected = re.sub(r"const P=\[.*?\];", js_block, html, flags=re.DOTALL)
after    = injected.count("{n:")
print(f"  ✓ Injected {after} entries into index.html")

unique_players = len({p["n"] for p in players})
unique_songs   = len({p["s"] for p in players})
with_artwork   = sum(1 for p in players if p.get("artworkUrl"))
with_preview   = sum(1 for p in players if p.get("p"))
print(f"\n  Unique players : {unique_players}")
print(f"  Unique songs   : {unique_songs}")
print(f"  With artwork   : {with_artwork}")
print(f"  With preview   : {with_preview}")

# ── Backup & write ────────────────────────────────────────────────────────────
backup = HERE / f"index_backup_{date.today()}.html"
shutil.copy(HTML_IN, backup)
HTML_IN.write_text(injected, encoding="utf-8")
print(f"\n  ✓ Backup → {backup.name}")
print(f"  ✓ index.html updated")

# ── Git push ──────────────────────────────────────────────────────────────────
def run(cmd):
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()

run(["git", "rm", "--cached", "index.html"])
code, out = run(["git", "add", "index.html"])
print(f"\n  git add    → {'✓' if code == 0 else '✗ ' + out}")

today_str = date.today().strftime("%Y-%m-%d")
code, out = run(["git", "commit", "-m",
    f"deploy: {today_str} — {unique_players} players, {unique_songs} songs"])
if "nothing to commit" in out:
    code, out = run(["git", "commit", "--allow-empty", "-m",
        f"deploy: {today_str} — {unique_players} players, {unique_songs} songs"])
print(f"  git commit → {'✓' if code == 0 else '✗ ' + out}")

code, out = run(["git", "push"])
if code == 0:
    print(f"  git push   → ✓")
    print(f"""
{'=' * 54}
  ✅ Live in ~30 seconds:
     https://walkup.socialsoundsystem.com

  Data: {data_date} · {unique_players} players · {unique_songs} songs
{'=' * 54}
""")
else:
    print(f"  git push   → ✗\n  {out}")
