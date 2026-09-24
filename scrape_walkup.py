"""
SocialSoundSystem — MLB Walk-Up Scraper
========================================
Scrapes all 30 MLB team music pages, enriches with Spotify metadata,
and outputs mlb.json for GitHub Pages.

SETUP (run once):
  pip install -r requirements.txt
  playwright install chromium

ENV VARS (set as GitHub Secrets or export locally):
  SPOTIFY_CLIENT_ID
  SPOTIFY_CLIENT_SECRET

RUN:
  python3 scrape_walkup.py

OUTPUT:
  mlb.json  —  served via GitHub Pages → fetched by deploy.py
"""

import json, re, time, os, base64
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

TODAY    = date.today().isoformat()
OUT_FILE = Path(__file__).parent / "sss-mlb.json"
PREV_FILE = Path(__file__).parent / "sss-mlb.prev.json"
DELAY    = 0.5  # seconds between Spotify API calls

TEAMS = [
    {"id":"angels",    "name":"Los Angeles Angels",      "url":"https://www.mlb.com/angels/ballpark/music"},
    {"id":"astros",    "name":"Houston Astros",           "url":"https://www.mlb.com/astros/ballpark/music"},
    {"id":"athletics", "name":"Oakland Athletics",        "url":"https://www.mlb.com/athletics/ballpark/music"},
    {"id":"bluejays",  "name":"Toronto Blue Jays",        "url":"https://www.mlb.com/bluejays/ballpark/music"},
    {"id":"braves",    "name":"Atlanta Braves",           "url":"https://www.mlb.com/braves/ballpark/music"},
    {"id":"brewers",   "name":"Milwaukee Brewers",        "url":"https://www.mlb.com/brewers/ballpark/music"},
    {"id":"cardinals", "name":"St. Louis Cardinals",      "url":"https://www.mlb.com/cardinals/ballpark/music"},
    {"id":"cubs",      "name":"Chicago Cubs",             "url":"https://www.mlb.com/cubs/ballpark/music"},
    {"id":"dbacks",    "name":"Arizona Diamondbacks",     "url":"https://www.mlb.com/dbacks/ballpark/music"},
    {"id":"dodgers",   "name":"Los Angeles Dodgers",      "url":"https://www.mlb.com/dodgers/ballpark/music"},
    {"id":"giants",    "name":"San Francisco Giants",     "url":"https://www.mlb.com/giants/ballpark/music"},
    {"id":"guardians", "name":"Cleveland Guardians",      "url":"https://www.mlb.com/guardians/ballpark/music"},
    {"id":"mariners",  "name":"Seattle Mariners",         "url":"https://www.mlb.com/mariners/ballpark/music"},
    {"id":"marlins",   "name":"Miami Marlins",            "url":"https://www.mlb.com/marlins/ballpark/music"},
    {"id":"mets",      "name":"New York Mets",            "url":"https://www.mlb.com/mets/ballpark/music"},
    {"id":"nationals", "name":"Washington Nationals",     "url":"https://www.mlb.com/nationals/ballpark/music"},
    {"id":"orioles",   "name":"Baltimore Orioles",        "url":"https://www.mlb.com/orioles/ballpark/music"},
    {"id":"padres",    "name":"San Diego Padres",         "url":"https://www.mlb.com/padres/ballpark/music"},
    {"id":"phillies",  "name":"Philadelphia Phillies",    "url":"https://www.mlb.com/phillies/ballpark/music"},
    {"id":"pirates",   "name":"Pittsburgh Pirates",       "url":"https://www.mlb.com/pirates/ballpark/music"},
    {"id":"rangers",   "name":"Texas Rangers",            "url":"https://www.mlb.com/rangers/ballpark/music"},
    {"id":"rays",      "name":"Tampa Bay Rays",           "url":"https://www.mlb.com/rays/ballpark/music"},
    {"id":"redsox",    "name":"Boston Red Sox",           "url":"https://www.mlb.com/redsox/ballpark/music"},
    {"id":"reds",      "name":"Cincinnati Reds",          "url":"https://www.mlb.com/reds/ballpark/music"},
    {"id":"rockies",   "name":"Colorado Rockies",         "url":"https://www.mlb.com/rockies/ballpark/music"},
    {"id":"royals",    "name":"Kansas City Royals",       "url":"https://www.mlb.com/royals/ballpark/music"},
    {"id":"tigers",    "name":"Detroit Tigers",           "url":"https://www.mlb.com/tigers/ballpark/music"},
    {"id":"twins",     "name":"Minnesota Twins",          "url":"https://www.mlb.com/twins/ballpark/music"},
    {"id":"whitesox",  "name":"Chicago White Sox",        "url":"https://www.mlb.com/whitesox/ballpark/music"},
    {"id":"yankees",   "name":"New York Yankees",         "url":"https://www.mlb.com/yankees/ballpark/music"},
]

# ── Spotify Auth ──────────────────────────────────────────────────────────────

_spotify_token = None
_token_expires = 0

def get_spotify_token():
    global _spotify_token, _token_expires
    if _spotify_token and time.time() < _token_expires - 60:
        return _spotify_token
    client_id     = os.environ["SPOTIFY_CLIENT_ID"]
    client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    _spotify_token = data["access_token"]
    _token_expires = time.time() + data["expires_in"]
    return _spotify_token

def spotify_search(song, artist):
    """Search Spotify for a track. Returns dict with id, preview_url, artwork, spotify_url."""
    try:
        token = get_spotify_token()
        q = f"track:{song}"
        if artist:
            q += f" artist:{artist}"
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": q, "type": "track", "limit": 1},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("tracks", {}).get("items", [])
        if not items:
            return {}
        t = items[0]
        images = t.get("album", {}).get("images", [])
        return {
            "id":         t["id"],
            "p":          t.get("preview_url") or "",
            "artworkUrl": images[0]["url"] if images else "",
            "spotifyUrl": t["external_urls"]["spotify"],
        }
    except Exception as e:
        print(f"      ⚠ Spotify lookup failed for '{song}': {e}")
        return {}

# ── HTML Parsing ──────────────────────────────────────────────────────────────

def parse_song_cell(td):
    """
    Parse the song/artist table cell.
    Returns list of dicts: [{s, a, spotifyUrl}]
    Fixes the concatenation bug — each <a> tag is one song.
    """
    songs = []
    anchors = td.find_all("a", href=True)

    spotify_anchors = [a for a in anchors if "spotify.com" in a.get("href", "")]

    if spotify_anchors:
        for a in spotify_anchors:
            raw = re.sub(r"\s+", " ", a.get_text()).strip()
            # Text format: "Song Title  Artist Name" (2+ spaces or newline)
            parts = re.split(r"\s{2,}", raw, maxsplit=1)
            song   = parts[0].strip() if parts else raw
            artist = parts[1].strip() if len(parts) > 1 else ""
            if song:
                songs.append({"s": song, "a": artist, "spotifyUrl": a["href"].split("?")[0]})
    else:
        # No Spotify links — parse plain text (e.g. Ohtani's unlicensed song)
        raw = re.sub(r"\s+", " ", td.get_text()).strip()
        parts = re.split(r"\s{2,}", raw, maxsplit=1)
        song   = parts[0].strip() if parts else ""
        artist = parts[1].strip() if len(parts) > 1 else ""
        if song and song.lower() not in ("song/artist", "song", ""):
            songs.append({"s": song, "a": artist, "spotifyUrl": ""})

    return songs


def parse_html(html, team_id):
    """Extract player rows from rendered HTML. Returns flat list of entries."""
    soup    = BeautifulSoup(html, "html.parser")
    results = []

    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue

        # Player name
        player_link = tds[0].find("a")
        if not player_link:
            continue
        name = re.sub(r"\s+", " ", player_link.get_text()).strip()
        if not name or name.lower() in ("player", "name"):
            continue

        # MLB player ID
        href  = player_link.get("href", "")
        mlb_id = re.search(r"/player/(\d+)", href)
        mlb_id = mlb_id.group(1) if mlb_id else None

        # Songs (fixed parsing)
        songs = parse_song_cell(tds[1])
        for song in songs:
            results.append({
                "n":    name,
                "t":    team_id,
                "mlbId": mlb_id,
                **song,
                "p":          song.get("spotifyUrl", ""),  # placeholder, enriched below
                "id":         None,
                "artworkUrl": "",
                "src":        "mlb.com",
                "upd":        TODAY,
            })

    return results


# ── Scraping ──────────────────────────────────────────────────────────────────

def scrape_team(page, team):
    print(f"  → {team['url']}")
    try:
        page.goto(team["url"], wait_until="networkidle", timeout=45000)
        page.wait_for_selector("table", timeout=15000)
        time.sleep(1.5)
    except Exception as e:
        print(f"    ⚠ Load error: {e}")
    html    = page.content()
    entries = parse_html(html, team["id"])
    print(f"    ✓ {len(entries)} song entries")
    return entries


# ── Spotify Enrichment ────────────────────────────────────────────────────────

def enrich_with_spotify(entries):
    """Add Spotify metadata to each entry. Caches by (song, artist) to avoid repeat calls."""
    cache = {}
    for i, e in enumerate(entries):
        key = (e["s"], e["a"])
        if key not in cache:
            time.sleep(DELAY)
            cache[key] = spotify_search(e["s"], e["a"])
        meta = cache[key]
        if meta:
            e["id"]         = meta.get("id")
            e["p"]          = meta.get("p", "")
            e["artworkUrl"] = meta.get("artworkUrl", "")
            e["spotifyUrl"] = meta.get("spotifyUrl") or e.get("spotifyUrl", "")
        if (i + 1) % 25 == 0:
            print(f"      Enriched {i+1}/{len(entries)}...")
    return entries


# ── Change Detection ──────────────────────────────────────────────────────────

def detect_changes(prev_players, curr_players):
    changes = []
    prev_map = {}
    for p in prev_players:
        prev_map[f"{p['n']}|{p['t']}"] = p.get("s", "")
    for p in curr_players:
        key    = f"{p['n']}|{p['t']}"
        before = prev_map.get(key)
        after  = p.get("s", "")
        if before and after and before != after:
            changes.append({"player": p["n"], "team": p["t"],
                            "from": before, "to": after, "date": TODAY})
    return changes


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    from playwright.sync_api import sync_playwright

    print(f"\n🎵 SocialSoundSystem — MLB Walk-Up Scraper")
    print(f"   {TODAY}\n{'─'*48}")

    # Validate Spotify creds early
    try:
        get_spotify_token()
        print("   ✓ Spotify auth OK\n")
    except Exception as e:
        print(f"   ✗ Spotify auth failed: {e}")
        print("     Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET\n")
        raise

    # Load previous run for change detection
    prev_players = []
    prev_changes = []
    if PREV_FILE.exists():
        try:
            prev = json.loads(PREV_FILE.read_text())
            prev_players = prev.get("players", [])
            prev_changes = prev.get("changes", [])
        except Exception:
            pass

    all_entries = []
    failed      = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx     = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()

        for i, team in enumerate(TEAMS, 1):
            print(f"[{i:02d}/{len(TEAMS)}] {team['name']}")
            entries = scrape_team(page, team)
            if entries:
                all_entries.extend(entries)
            else:
                failed.append(team["id"])
                print(f"    ✗ No data")
            time.sleep(1.5)

        browser.close()

    print(f"\n{'─'*48}")
    print(f"📀 Enriching {len(all_entries)} entries with Spotify...")
    all_entries = enrich_with_spotify(all_entries)

    # Detect walk-up changes
    changes = detect_changes(prev_players, all_entries)
    if changes:
        print(f"\n🔄 {len(changes)} change(s) detected:")
        for c in changes:
            print(f"   {c['player']} ({c['team']}): \"{c['from']}\" → \"{c['to']}\"")

    all_changes = (changes + prev_changes)[:100]

    output = {
        "schema":    1,
        "source":    "socialsoundsystem.com",
        "dataAsOf":  TODAY,
        "stats": {
            "totalEntries":   len(all_entries),
            "uniquePlayers":  len({e["n"] for e in all_entries}),
            "teamsWithData":  len({e["t"] for e in all_entries}),
            "emptyTeams":     failed,
        },
        "players": all_entries,
        "changes": all_changes,
    }

    # Save current as prev for next run
    PREV_FILE.write_text(json.dumps({"players": all_entries, "changes": all_changes}))
    OUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"\n✅ Done!")
    print(f"   Entries  : {len(all_entries)}")
    print(f"   Players  : {len({e['n'] for e in all_entries})}")
    print(f"   Teams    : {len({e['t'] for e in all_entries})}")
    print(f"   Output   : {OUT_FILE}")
    if failed:
        print(f"\n⚠  Empty teams: {', '.join(failed)}")

if __name__ == "__main__":
    main()
