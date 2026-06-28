from flask import Flask, render_template, jsonify, session, redirect, request
import json, threading, urllib.request, os, requests as req_lib
from pathlib import Path
from collections import OrderedDict
from datetime import date, timedelta, datetime, timezone

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

# ── Database ─────────────────────────────────────────────────────────────────
import psycopg2, psycopg2.extras

def _get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")

def _init_db():
    try:
        with _get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        discord_id   TEXT PRIMARY KEY,
                        username     TEXT,
                        last_ip      TEXT,
                        first_login  TIMESTAMPTZ DEFAULT NOW(),
                        last_login   TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
    except Exception as e:
        print(f"[db] init error: {e}")

def _record_login(user, ip=None):
    try:
        with _get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (discord_id, username, last_ip, first_login, last_login)
                    VALUES (%s, %s, %s, NOW(), NOW())
                    ON CONFLICT (discord_id) DO UPDATE
                      SET username = EXCLUDED.username, last_ip = EXCLUDED.last_ip, last_login = NOW()
                """, (user["id"], user["username"], ip))
    except Exception as e:
        print(f"[db] record_login error: {e}")

threading.Thread(target=_init_db, daemon=True).start()

DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")

@app.route("/login")
def login():
    return redirect(
        "https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        "&response_type=code&scope=identify"
    )

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect("/")
    try:
        r = req_lib.post("https://discord.com/api/oauth2/token", data={
            "client_id":     DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  DISCORD_REDIRECT_URI,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        token = r.json().get("access_token")
        if not token:
            return redirect("/")
        user = req_lib.get("https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {token}"}).json()
        session["user"] = {
            "id":       user["id"],
            "username": user["username"],
            "avatar":   user.get("avatar"),
        }
        ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
        _record_login(session["user"], ip)
    except Exception as e:
        print(f"[discord oauth] error: {e}")
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/api/me")
def api_me():
    return jsonify(session.get("user"))


BASE = Path(__file__).parent

# Linear regression fit from JP→global offset analysis (545 unconfirmed events)
# offset_days = _JP_SLOPE * jp_unix_seconds + _JP_INTERCEPT
_JP_SLOPE     = -0.2408 / 86400
_JP_INTERCEPT = 6059.8

def _jp_to_global(jp_date_str: str) -> str:
    """Estimate global release date from a JP date string (YYYY-MM-DD)."""
    jp_dt = datetime.fromisoformat(jp_date_str).replace(tzinfo=timezone.utc)
    offset_days = _JP_SLOPE * jp_dt.timestamp() + _JP_INTERCEPT
    gl_ts = jp_dt.timestamp() + offset_days * 86400
    return datetime.fromtimestamp(gl_ts, timezone.utc).strftime("%Y-%m-%d")

def _anniv_display_name(name: str) -> str:
    import re
    m = re.match(r'^([\d.]+) Year Anniversary', name)
    if not m:
        return name
    num_str = m.group(1)
    n = float(num_str)
    if n == int(n):
        i = int(n)
        suffix = "th" if 11 <= i <= 13 else {1:"st",2:"nd",3:"rd"}.get(i % 10, "th")
        return f"{i}{suffix} Anniversary"
    return f"{num_str}th Anniversary"

def _is_character(card):
    return "/characters/" in card.get("url", "")

def _card_remote_url(card):
    cid = card["id"]
    if _is_character(card):
        return f"https://gametora.com/images/umamusume/characters/chara_stand_{cid[:4]}_{cid}.png"
    return f"https://uma.guide/img/card/composite/tex_support_card_{cid}.webp"

def _card_local_url(card):
    if _is_character(card):
        return f"/static/gametora/characters/{card['id']}.png"
    return f"/static/uma guide/{card['id']}.webp"

def _card_local_path(card):
    if _is_character(card):
        return BASE / "static" / "gametora" / "characters" / f"{card['id']}.png"
    return BASE / "static" / "uma guide" / f"{card['id']}.webp"

_UA_GAMETORA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36", "Referer": "https://gametora.com/"}
_UA_UMA      = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36", "Referer": "https://uma.guide/"}

def _load_custom_banners():
    custom_path = BASE / "custom_banners.json"
    if not custom_path.exists():
        return []
    try:
        entries = json.loads(custom_path.read_text(encoding="utf-8"))
        result = []
        for b in entries:
            if not b.get("banner_name") or b.get("_note") or b.get("_comment") or b.get("_schema"):
                continue
            if not b.get("start_date"):
                b["start_date"] = b.get("_estimated_start_date") or (
                    _jp_to_global(b["jp_start_date"]) if b.get("jp_start_date") else None)
            if not b.get("end_date"):
                b["end_date"] = b.get("_estimated_end_date") or (
                    _jp_to_global(b["jp_end_date"]) if b.get("jp_end_date") else None)
            result.append(b)
        return result
    except Exception as e:
        print(f"[custom_banners] Error loading: {e}")
        return []

def _download_all_cards():
    raw = json.loads((BASE / "timeline_banners_output.json").read_text(encoding="utf-8"))
    raw = raw + _load_custom_banners()
    for b in raw:
        for card in (b.get("cards") or [])[:2]:
            dest = _card_local_path(card)
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            headers = _UA_GAMETORA if _is_character(card) else _UA_UMA
            try:
                req = urllib.request.Request(_card_remote_url(card), headers=headers)
                with urllib.request.urlopen(req) as r:
                    dest.write_bytes(r.read())
            except Exception:
                pass

threading.Thread(target=_download_all_cards, daemon=True).start()

def _make_card(card):
    dest = _card_local_path(card)
    return {
        "name": card["name"],
        "img":  _card_local_url(card) if dest.exists() else _card_remote_url(card),
        "url":  card.get("uma_url") or card.get("url", ""),
    }

def _strip_banner(name):
    for suffix in (" Support Banner", " Banner"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name

def _sorted_cards(b):
    return sorted((b.get("cards") or []), key=lambda c: 0 if "SSR" in c["name"] else 1)

def _assign_meeting_numbers(raw):
    """Assign meeting_number to all CM and LoH banners in-place, sorted by start date."""
    loh_counter = 1
    last_official_cm = max(
        (int(b["banner_id"].split("-")[-1]) for b in raw
         if b.get("type") == "champions_meeting" and (b.get("banner_id") or "").startswith("champions-meeting-")),
        default=29
    )
    custom_cm_counter = last_official_cm + 2
    for b in sorted(raw, key=lambda x: (x.get("start_date") or "")[:10]):
        bid = b.get("banner_id", "") or ""
        if b.get("type") == "champions_meeting":
            if bid.startswith("champions-meeting-"):
                b["meeting_number"] = int(bid.split("-")[-1]) + 1
            elif bid.startswith("cm-"):
                b["meeting_number"] = custom_cm_counter
                custom_cm_counter += 1
        elif b.get("type") == "league_of_heroes":
            b["meeting_number"] = loh_counter
            loh_counter += 1

@app.route("/")
def index():
    raw = json.loads((BASE / "timeline_banners_output.json").read_text(encoding="utf-8"))
    raw = raw + _load_custom_banners()
    _assign_meeting_numbers(raw)
    def _banner_name(b):
        if b["type"] == "support" and b.get("cards"):
            cards = _sorted_cards(b)
            return ", ".join(c["name"] for c in cards)
        if b["type"] in ("anniversary", "step_up"):
            return _anniv_display_name(b["banner_name"])
        return _strip_banner(b["banner_name"])

    banners = [
        {
            "name":  _banner_name(b),
            "type":  b["type"],
            "start": (b.get("start_date") or "")[:10],
            "end":   (b.get("end_date")   or "")[:10],
            "meeting_number": b.get("meeting_number"),
            "cards":  [_make_card(c) for c in _sorted_cards(b)[:2]],
            "card_names": [c["name"] for c in _sorted_cards(b)],
            "events":  [{"name": e["name"], "amount": e["amount"]} for e in (b.get("events") or [])],
            "rewards": b.get("rewards") or {"uma_ticket": 0, "support_ticket": 0, "ssr": 0, "sr": 0},
        "free":   b.get("free") or 0,
        }
        for b in raw if b.get("banner_name")
    ]
    anniversaries = _get_anniversaries()
    pack_events_path = BASE / "pack_events.json"
    if pack_events_path.exists():
        try:
            today = date.today().isoformat()
            extras = []
            raw_pe = json.loads(pack_events_path.read_text(encoding="utf-8"))
            for e in (raw_pe.get("events", []) if isinstance(raw_pe, dict) else raw_pe):
                if not e.get("start") and e.get("jp_start"):
                    e["start"] = e.get("_estimated_start") or _jp_to_global(e["jp_start"])
                    e.setdefault("date", e.get("_estimated_date") or (
                        datetime.strptime(e["start"], "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0", " ") + " (est.)"))
                    e.setdefault("is_confirmed", False)
                elif e.get("start") and "is_confirmed" not in e:
                    e["is_confirmed"] = not bool(e.get("step_up_banner"))
                if e.get("start") and not e.get("date"):
                    e["date"] = datetime.strptime(e["start"], "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0", " ")
                if (e.get("start") or "") >= today:
                    extras.append(e)
            existing_names = {a["name"] for a in anniversaries}
            anniversaries += [e for e in extras if e.get("name") not in existing_names or e.get("step_up_banner")]
            anniversaries.sort(key=lambda e: e.get("start") or "")
        except Exception as _pe_err:
            print(f"[pack_events] Error loading pack_events.json: {_pe_err}")
    pack_uma     = _enrich_pack(json.loads((BASE / "pack_uma.json").read_text(encoding="utf-8")),     is_char=True)
    pack_support = _enrich_pack(json.loads((BASE / "pack_support.json").read_text(encoding="utf-8")), is_char=False)
    return render_template("index.html", banners=banners, anniversaries=anniversaries,
                           pack_uma=pack_uma, pack_support=pack_support,
                           user=session.get("user"))

@app.route("/debug-packs")
def debug_packs():
    try:
        pack_events_path = BASE / "pack_events.json"
        raw = json.loads(pack_events_path.read_text(encoding="utf-8"))
        events = raw.get("events", []) if isinstance(raw, dict) else raw
        today = date.today().isoformat()
        result = []
        for e in events:
            entry = dict(e)
            if not entry.get("start") and entry.get("jp_start"):
                entry["start"] = _jp_to_global(entry["jp_start"])
            entry["passes_date_filter"] = (entry.get("start") or "") >= today
            result.append(entry)
        anniv_names = [a["name"] for a in _get_anniversaries()]
        return jsonify({"events": result, "existing_anniv_names": anniv_names})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/refresh", methods=["POST"])
def refresh():
    import importlib, sys
    sys.path.insert(0, str(BASE))
    try:
        import sync_dates
        importlib.reload(sync_dates)
        sync_dates.sync()
    except Exception as e:
        pass  # dantsu bot files may not be available

    # Ensure uma_url exists on all cards (for any newly added banners)
    raw = json.loads((BASE / "timeline_banners_output.json").read_text(encoding="utf-8"))
    changed = False
    for b in raw:
        for card in (b.get("cards") or []):
            if not card.get("uma_url"):
                cid = card["id"]
                card["uma_url"] = (
                    f"https://uma.guide/characters/detail?card={cid}"
                    if _is_character(card)
                    else f"https://uma.guide/support-cards/detail?id={cid}"
                )
                changed = True
    if changed:
        (BASE / "timeline_banners_output.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    _download_all_cards()
    return jsonify(ok=True)

@app.route("/updates")
def updates():
    try:
        log = json.loads((BASE / "updates_log.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        log = []
    log_sorted = sorted(log, key=lambda e: e.get("timestamp", ""), reverse=True)
    return render_template("updates.html", log=log_sorted)

def _enrich_pack(entries, is_char):
    out = []
    for e in entries:
        if "_marker" in e:
            out.append(e)
            continue
        cid = e["id"]
        if is_char:
            local = BASE / "static" / "gametora" / "characters" / f"{cid}.png"
            img = f"/static/gametora/characters/{cid}.png" if local.exists() \
                  else f"https://gametora.com/images/umamusume/characters/chara_stand_{cid[:4]}_{cid}.png"
        else:
            local = BASE / "static" / "uma guide" / f"{cid}.webp"
            img = f"/static/uma guide/{cid}.webp" if local.exists() \
                  else f"https://uma.guide/img/card/composite/tex_support_card_{cid}.webp"
        out.append({**e, "img": img})
    return out

def _get_anniversaries():
    import re
    from datetime import datetime
    raw = json.loads((BASE / "timeline_banners_output.json").read_text(encoding="utf-8"))
    today = date.today().isoformat()

    result = []
    for b in raw:
        if b.get("type") != "anniversary":
            continue
        start = (b.get("start_date") or "")[:10]
        if not start or start < today:
            continue
        from datetime import datetime as dt_
        result.append({
            "name":         _anniv_display_name(b.get("banner_name", "")),
            "date":         dt_.fromisoformat(start).strftime("%B %d, %Y").replace(" 0", " "),
            "id":           f"e{b.get('index', 0)}",
            "start":        start,
            "end":          (b.get("end_date") or "")[:10],
            "is_confirmed": b.get("is_confirmed", False),
        })
    return result

@app.route("/packs")
def packs():
    anniversaries = _get_anniversaries()
    pack_events_path = BASE / "pack_events.json"
    if pack_events_path.exists():
        try:
            today = date.today().isoformat()
            extras = []
            raw_pe = json.loads(pack_events_path.read_text(encoding="utf-8"))
            for e in (raw_pe.get("events", []) if isinstance(raw_pe, dict) else raw_pe):
                if not e.get("start") and e.get("jp_start"):
                    e["start"] = e.get("_estimated_start") or _jp_to_global(e["jp_start"])
                    e.setdefault("date", e.get("_estimated_date") or (
                        datetime.strptime(e["start"], "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0", " ") + " (est.)"))
                    e.setdefault("is_confirmed", False)
                elif e.get("start") and "is_confirmed" not in e:
                    e["is_confirmed"] = not bool(e.get("step_up_banner"))
                if e.get("start") and not e.get("date"):
                    e["date"] = datetime.strptime(e["start"], "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0", " ")
                if (e.get("start") or "") >= today:
                    extras.append(e)
            existing_names = {a["name"] for a in anniversaries}
            anniversaries += [e for e in extras if e.get("name") not in existing_names or e.get("step_up_banner")]
            anniversaries.sort(key=lambda e: e.get("start") or "")
        except Exception as _pe_err:
            print(f"[pack_events] Error loading pack_events.json: {_pe_err}")
    pack_uma     = _enrich_pack(json.loads((BASE / "pack_uma.json").read_text(encoding="utf-8")),     is_char=True)
    pack_support = _enrich_pack(json.loads((BASE / "pack_support.json").read_text(encoding="utf-8")), is_char=False)
    return render_template("packs.html", anniversaries=anniversaries,
                           pack_uma=pack_uma, pack_support=pack_support,
                           user=session.get("user"))

@app.route("/cards")
def cards():
    # Build card → earliest banner date map from timeline data
    raw = json.loads((BASE / "timeline_banners_output.json").read_text(encoding="utf-8"))
    raw = raw + _load_custom_banners()
    card_first_date = {}
    banner_cards = {}
    for b in raw:
        start = (b.get("start_date") or "")[:10]
        for card in (b.get("cards") or []):
            cid = card["id"]
            if _is_character(card):
                continue
            if "SSR" not in card.get("name", ""):
                continue
            if cid not in card_first_date or (start and start < card_first_date[cid]):
                card_first_date[cid] = start
            if cid not in banner_cards:
                dest = _card_local_path(card)
                banner_cards[cid] = {
                    "id":   cid,
                    "name": card["name"],
                    "img":  _card_local_url(card) if dest.exists() else _card_remote_url(card),
                }

    # Fill in any SSR supports from pack_support.json not yet seen
    pack_support = json.loads((BASE / "pack_support.json").read_text(encoding="utf-8"))
    for entry in pack_support:
        if "_marker" in entry or "id" not in entry:
            continue
        if "SSR" not in entry.get("name", ""):
            continue
        cid = entry["id"]
        if cid not in banner_cards:
            local = BASE / "static" / "uma guide" / f"{cid}.webp"
            img = f"/static/uma guide/{cid}.webp" if local.exists() \
                  else f"https://uma.guide/img/card/composite/tex_support_card_{cid}.webp"
            banner_cards[cid] = {"id": cid, "name": entry["name"], "img": img}

    all_cards = [
        {**c, "release_date": card_first_date.get(c["id"], "")}
        for c in banner_cards.values()
    ]
    all_cards.sort(key=lambda c: c["name"])

    # Banners list for 200-pull detection: name, type, card IDs, start date
    # Use the same name processing as BANNER_DATA so it matches caratCalc_v1 rows
    banners_simple = []
    for b in raw:
        card_ids = [
            c["id"] for c in (b.get("cards") or [])
            if not _is_character(c) and "SSR" in c.get("name", "")
        ]
        if not card_ids:
            continue
        btype = b.get("type", "")
        if btype == "support" and b.get("cards"):
            display_name = ", ".join(c["name"] for c in _sorted_cards(b))
            ssr_names = [c["name"] for c in _sorted_cards(b) if "SSR" in c.get("name", "")]
            short_name = ", ".join(ssr_names) if ssr_names else display_name
        elif btype in ("anniversary", "step_up"):
            display_name = _anniv_display_name(b.get("banner_name", ""))
            short_name = display_name
        else:
            display_name = _strip_banner(b.get("banner_name", ""))
            short_name = display_name
        banners_simple.append({
            "name":       display_name,
            "short_name": short_name,
            "start": (b.get("start_date") or "")[:10],
            "card_ids": card_ids,
        })

    # Pack events for selector labels: id, name, start, selector_labels
    anniversaries = _get_anniversaries()
    pack_events_path = BASE / "pack_events.json"
    pack_events_simple = []
    if pack_events_path.exists():
        try:
            today = date.today().isoformat()
            raw_pe = json.loads(pack_events_path.read_text(encoding="utf-8"))
            all_pe = raw_pe.get("events", []) if isinstance(raw_pe, dict) else raw_pe
            seen_names = set()
            for e in all_pe:
                if not e.get("start") and e.get("jp_start"):
                    e["start"] = _jp_to_global(e["jp_start"])
                pack_events_simple.append({
                    "id":    e.get("id") or f"e{all_pe.index(e)}",
                    "name":  e.get("name", ""),
                    "start": (e.get("start") or "")[:10],
                    "selector_labels": e.get("selector_labels") or {},
                })
        except Exception:
            pass
    for a in anniversaries:
        pack_events_simple.append({
            "id":    a["id"],
            "name":  a["name"],
            "start": a["start"],
            "selector_labels": {},
        })

    # Timeline rewards by date for resource projection
    timeline_rewards = []
    for b in raw:
        start = (b.get("start_date") or "")[:10]
        rw = b.get("rewards") or {}
        ssr = rw.get("ssr", 0) or 0
        sr  = rw.get("sr",  0) or 0
        uma = rw.get("uma_ticket", 0) or 0
        sup = rw.get("support_ticket", 0) or 0
        if start and (ssr or sr or uma or sup):
            timeline_rewards.append({"date": start, "ssr": ssr, "sr": sr, "uma": uma, "sup": sup})
    timeline_rewards.sort(key=lambda x: x["date"])

    # Character banners for Uma acquisition tracking (matched against caratCalc_v1 row.banner)
    char_banners_simple = []
    for b in raw:
        btype = b.get("type", "")
        char_card_names = [c["name"] for c in (b.get("cards") or []) if _is_character(c)]
        if not char_card_names:
            continue
        if btype == "character":
            display_name = _strip_banner(b.get("banner_name", ""))
        elif btype in ("anniversary", "step_up"):
            display_name = _anniv_display_name(b.get("banner_name", ""))
        else:
            continue
        char_banners_simple.append({
            "name":       display_name,
            "start":      (b.get("start_date") or "")[:10],
            "card_names": char_card_names,
        })

    pack_uma = _enrich_pack(json.loads((BASE / "pack_uma.json").read_text(encoding="utf-8")), is_char=True)

    return render_template("cards.html", all_cards=all_cards,
                           banners_simple=banners_simple,
                           pack_events_simple=pack_events_simple,
                           timeline_rewards=timeline_rewards,
                           char_banners_simple=char_banners_simple,
                           pack_uma=pack_uma)

@app.route("/data")
def data():
    return render_template("data.html")

@app.route("/timeline")
def timeline():
    raw = json.loads((BASE / "timeline_banners_output.json").read_text(encoding="utf-8"))
    raw = raw + _load_custom_banners()
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    def _show(b):
        end   = (b.get("end_date")   or "")[:10]
        start = (b.get("start_date") or "")[:10]
        if end:   return end >= today
        if start: return start >= cutoff
        return True
    UNGROUPED = {"anniversary", "step_up", "champions_meeting", "league_of_heroes"}
    TYPE_ORDER = {"anniversary": 0, "character": 1, "support": 2, "step_up": 3, "champions_meeting": 4, "league_of_heroes": 5}
    banners = sorted(
        [b for b in raw if _show(b)],
        key=lambda b: (
            (b.get("start_date") or "")[:10],
            TYPE_ORDER.get(b.get("type", ""), 9),
        )
    )
    _assign_meeting_numbers(raw)
    # group character/support by date; anniversary/champions_meeting/league_of_heroes always standalone
    raw_groups = []  # list of [date_label, [banners]]
    for b in banners:
        start = (b.get("start_date") or "")[:10] or "Unknown"
        if b.get("type") in UNGROUPED:
            raw_groups.append([start, [b]])
        elif raw_groups and raw_groups[-1][0] == start and b.get("type") not in UNGROUPED and raw_groups[-1][1][0].get("type") not in UNGROUPED:
            raw_groups[-1][1].append(b)
        else:
            raw_groups.append([start, [b]])
    # hoist events to group level (deduped by name); process card images
    groups = []
    for date_label, group_banners in raw_groups:
        seen, events = set(), []
        reward_totals = {"uma_ticket": 0, "support_ticket": 0, "ssr": 0, "sr": 0}
        for b in group_banners:
            sorted_cards = _sorted_cards(b)
            if b.get("type") in ("anniversary", "step_up"):
                b["banner_name"] = _anniv_display_name(b.get("banner_name") or "")
            elif b.get("type") in ("character", "support") and sorted_cards:
                b["banner_name"] = ", ".join(c["name"] for c in sorted_cards)
            else:
                b["banner_name"] = _strip_banner(b.get("banner_name") or "")
            b["cards"] = [_make_card(c) for c in sorted_cards]
            within_count = {}
            for ev in (b.get("events") or []):
                within_count[ev["name"]] = within_count.get(ev["name"], 0) + 1
                ev_key = ev["name"] + "|" + str(within_count[ev["name"]])
                if ev_key not in seen:
                    seen.add(ev_key)
                    events.append(ev)
            for k in reward_totals:
                reward_totals[k] += (b.get("rewards") or {}).get(k, 0)
        REWARD_LABELS = {"uma_ticket": "Uma Tickets", "support_ticket": "Support Tickets", "ssr": "SSR Shards", "sr": "SR Shards"}
        rewards = [{"name": REWARD_LABELS[k], "amount": v, "key": k} for k, v in reward_totals.items() if v > 0]
        end_dates = [b.get("end_date", "")[:10] for b in group_banners if b.get("end_date")]
        end_date = max(end_dates) if end_dates else None
        groups.append({"date": date_label, "end_date": end_date, "banners": group_banners, "events": events, "rewards": rewards})
    return render_template("timeline.html", groups=groups)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=False, port=port, host="0.0.0.0")
