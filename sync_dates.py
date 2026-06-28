import json
import os
import shutil
from datetime import datetime, date, timezone
from pathlib import Path

# Same linear regression as app.py — update both if the formula changes
_JP_SLOPE     = -0.2408 / 86400
_JP_INTERCEPT = 6059.8

def _jp_to_global(jp_date_str: str) -> str:
    jp_dt = datetime.fromisoformat(jp_date_str).replace(tzinfo=timezone.utc)
    offset_days = _JP_SLOPE * jp_dt.timestamp() + _JP_INTERCEPT
    gl_ts = jp_dt.timestamp() + offset_days * 86400
    return datetime.utcfromtimestamp(gl_ts).strftime("%Y-%m-%d")

BASE = Path(__file__).parent
DANTSU_BOT = BASE.parent / "dantsu bot"
OUTPUT_FILE = str(BASE / "timeline_banners_output.json")

def backup(path: Path):
    if not path.exists():
        return
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = BASE / "backups" / f"{path.stem}_{ts}{path.suffix}"
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(path, dest)

_LOCAL_TIMELINE = BASE / "timeline.json"
_DANTSU_TIMELINE = DANTSU_BOT / "timeline.json"
TIMELINE_FILE = str(_LOCAL_TIMELINE if _LOCAL_TIMELINE.exists() else _DANTSU_TIMELINE)


def load_timeline():
    with open(TIMELINE_FILE, encoding="utf-8") as f:
        return json.load(f)


UPDATES_FILE = str(BASE / "updates_log.json")


def _load_updates():
    try:
        with open(UPDATES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_updates(log):
    backup(Path(UPDATES_FILE))
    with open(UPDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def sync():
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        output = json.load(f)

    tl = load_timeline()

    today = date.today().isoformat()
    now   = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log   = _load_updates()
    added_to_log = 0

    # Build lookups from timeline.json
    anniv_by_label = {a["label"]: a for a in tl.get("anniversaries", [])}
    banner_by_gacha = {
        str(e["gacha_id"]): e
        for e in tl.get("events", [])
        if e.get("type") in ("character_banner", "support_card_banner")
    }
    champ_by_id = {
        e["id"]: e
        for e in tl.get("events", [])
        if e.get("type") == "champions_meeting"
    }

    # Track what's already in the output file
    existing_anniv_names = {e["banner_name"] for e in output if e["type"] == "anniversary"}
    existing_banner_ids  = {str(e["banner_id"]) for e in output if e.get("banner_id")}

    updated = 0

    # ── Update existing entries (dates only) ─────────────────────────
    for entry in output:
        t = entry["type"]
        if t == "anniversary":
            src = anniv_by_label.get(entry["banner_name"])
            if src:
                new_start = src.get("global_date")
                if new_start and entry.get("start_date") != new_start:
                    log.append({"timestamp": now, "kind": "date_change", "event_type": t,
                                "name": entry["banner_name"], "field": "start_date",
                                "old": entry.get("start_date"), "new": new_start})
                    entry["start_date"] = new_start
                    updated += 1; added_to_log += 1

        elif t in ("character", "support"):
            src = banner_by_gacha.get(str(entry.get("banner_id", "")))
            if src:
                changed = False
                new_start = src.get("global_release_date")
                new_end   = src.get("estimated_end_date")
                if new_start and entry.get("start_date") != new_start:
                    log.append({"timestamp": now, "kind": "date_change", "event_type": t,
                                "name": entry["banner_name"], "field": "start_date",
                                "old": entry.get("start_date"), "new": new_start})
                    entry["start_date"] = new_start
                    changed = True; added_to_log += 1
                if entry.get("end_date") != new_end:
                    log.append({"timestamp": now, "kind": "date_change", "event_type": t,
                                "name": entry["banner_name"], "field": "end_date",
                                "old": entry.get("end_date"), "new": new_end})
                    entry["end_date"] = new_end
                    changed = True; added_to_log += 1
                if changed:
                    updated += 1

        elif t == "champions_meeting":
            src = champ_by_id.get(str(entry.get("banner_id", "")))
            if src:
                changed = False
                new_start = src.get("global_release_date")
                new_end   = src.get("estimated_end_date")
                if new_start and entry.get("start_date") != new_start:
                    log.append({"timestamp": now, "kind": "date_change", "event_type": t,
                                "name": entry["banner_name"], "field": "start_date",
                                "old": entry.get("start_date"), "new": new_start})
                    entry["start_date"] = new_start
                    changed = True; added_to_log += 1
                if entry.get("end_date") != new_end:
                    log.append({"timestamp": now, "kind": "date_change", "event_type": t,
                                "name": entry["banner_name"], "field": "end_date",
                                "old": entry.get("end_date"), "new": new_end})
                    entry["end_date"] = new_end
                    changed = True; added_to_log += 1
                if changed:
                    updated += 1

    # ── Add new entries (future only) ────────────────────────────────
    for ann in tl.get("anniversaries", []):
        if ann["label"] in existing_anniv_names:
            continue
        if (ann.get("global_date") or "")[:10] < today:
            continue
        output.append({
            "type":        "anniversary",
            "banner_id":   None,
            "banner_name": ann["label"],
            "start_date":  ann.get("global_date"),
            "end_date":    None,
            "is_confirmed": ann.get("is_confirmed", False),
            "index":       ann.get("index", 0),
            "free":        0,
            "cards":       [],
            "events":      [],
            "rewards":     {"uma_ticket": 0, "support_ticket": 0, "ssr": 0, "sr": 0},
        })
        log.append({"timestamp": now, "kind": "new_event", "event_type": "anniversary",
                    "name": ann["label"], "start_date": ann.get("global_date")})
        updated += 1; added_to_log += 1

    for e in tl.get("events", []):
        etype = e.get("type")
        if etype not in ("character_banner", "support_card_banner", "champions_meeting"):
            continue
        bid = str(e.get("gacha_id") or e.get("id", ""))
        if bid in existing_banner_ids:
            continue
        if (e.get("global_release_date") or "")[:10] < today:
            continue
        out_type = "champions_meeting" if etype == "champions_meeting" else ("character" if etype == "character_banner" else "support")
        output.append({
            "type":        out_type,
            "banner_id":   bid,
            "banner_name": e.get("title", ""),
            "start_date":  e.get("global_release_date"),
            "end_date":    e.get("estimated_end_date"),
            "is_confirmed": e.get("is_confirmed", False),
            "free":        0,
            "cards":       [],
            "events":      [],
            "rewards":     {"uma_ticket": 0, "support_ticket": 0, "ssr": 0, "sr": 0},
        })
        log.append({"timestamp": now, "kind": "new_event", "event_type": out_type,
                    "name": e.get("title", ""), "start_date": e.get("global_release_date")})
        updated += 1; added_to_log += 1

    backup(Path(OUTPUT_FILE))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # ── Update estimated dates in pack_events.json ───────────────────
    pack_events_path = BASE / "pack_events.json"
    custom_banners_path = BASE / "custom_banners.json"
    if pack_events_path.exists():
        try:
            raw_pe = json.loads(pack_events_path.read_text(encoding="utf-8"))
            events = raw_pe.get("events", []) if isinstance(raw_pe, dict) else raw_pe
            pe_changed = 0

            # Build lookup of step_up custom banners by banner_name
            step_up_by_name: dict[str, dict] = {}
            if custom_banners_path.exists():
                try:
                    cb_entries = json.loads(custom_banners_path.read_text(encoding="utf-8"))
                    for b in cb_entries:
                        if b.get("type") == "step_up" and b.get("banner_name") and not b.get("_schema") and not b.get("_comment"):
                            step_up_by_name[b["banner_name"]] = b
                except Exception:
                    pass

            # Sync step_up-linked events: copy name and start from the custom banner
            existing_names = {e.get("name") for e in events}
            for su_name, su in step_up_by_name.items():
                if su_name not in existing_names:
                    # Auto-create the pack_event entry for this step_up (global dates only)
                    new_id = f"stepup-{su.get('banner_id', su_name.lower().replace(' ', '-'))}"
                    new_entry: dict = {
                        "name":            su_name,
                        "id":              new_id,
                        "step_up_banner":  su_name,
                        "packs":           [],
                        "selectors":       ["s21uma"],
                        "selector_labels": {"s21uma": "★3", "s70uma": "★3", "s21ssr": "SSR", "s70ssr": "SSR"},
                    }
                    if su.get("start_date"):
                        new_entry["start"] = su["start_date"]
                    events.append(new_entry)
                    existing_names.add(su_name)
                    log.append({"timestamp": now, "kind": "new_event", "event_type": "pack_event_step_up",
                                "name": su_name})
                    added_to_log += 1
                    pe_changed += 1
                    print(f"[sync] Added step_up pack event: {su_name}")
                else:
                    # Update start on existing step_up-linked entry if date changed
                    for e in events:
                        if e.get("name") != su_name or not e.get("step_up_banner"):
                            continue
                        new_start = su.get("start_date")
                        if new_start and e.get("start") != new_start:
                            e["start"] = new_start
                            pe_changed += 1

            for e in events:
                if not e.get("jp_start") or e.get("start"):
                    continue  # skip if no jp_start or if user has set an explicit start
                new_start = _jp_to_global(e["jp_start"])
                new_date  = datetime.strptime(new_start, "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0", " ") + " (est.)"
                old_start = e.get("_estimated_start")
                if old_start and old_start != new_start:
                    log.append({"timestamp": now, "kind": "date_change", "event_type": "pack_event",
                                "name": e.get("name", ""), "field": "estimated_start",
                                "old": old_start, "new": new_start})
                    added_to_log += 1
                e["_estimated_start"] = new_start
                e["_estimated_date"]  = new_date
                pe_changed += 1
            if pe_changed:
                backup(pack_events_path)
                pack_events_path.write_text(
                    json.dumps(raw_pe, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except Exception as _pe_err:
            print(f"[sync] pack_events update error: {_pe_err}")

    # ── Update estimated dates in custom_banners.json ────────────────────
    if custom_banners_path.exists():
        try:
            entries = json.loads(custom_banners_path.read_text(encoding="utf-8"))
            cb_changed = 0
            for b in entries:
                if not b.get("banner_name") or b.get("_note") or b.get("_comment") or b.get("_schema"):
                    continue
                if b.get("type") == "step_up":
                    continue  # step_up banners use global dates only
                changed = False
                if b.get("jp_start_date") and not b.get("start_date"):
                    new_start = _jp_to_global(b["jp_start_date"])
                    if b.get("_estimated_start_date") != new_start:
                        if b.get("_estimated_start_date"):
                            log.append({"timestamp": now, "kind": "date_change", "event_type": "custom_banner",
                                        "name": b.get("banner_name", ""), "field": "estimated_start_date",
                                        "old": b["_estimated_start_date"], "new": new_start})
                            added_to_log += 1
                        b["_estimated_start_date"] = new_start
                        changed = True
                if b.get("jp_end_date") and not b.get("end_date"):
                    new_end = _jp_to_global(b["jp_end_date"])
                    if b.get("_estimated_end_date") != new_end:
                        if b.get("_estimated_end_date"):
                            log.append({"timestamp": now, "kind": "date_change", "event_type": "custom_banner",
                                        "name": b.get("banner_name", ""), "field": "estimated_end_date",
                                        "old": b["_estimated_end_date"], "new": new_end})
                            added_to_log += 1
                        b["_estimated_end_date"] = new_end
                        changed = True
                if changed:
                    cb_changed += 1
            if cb_changed:
                backup(custom_banners_path)
                custom_banners_path.write_text(
                    json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(f"[sync] Updated {cb_changed} custom banner(s) with estimated dates")
        except Exception as _cb_err:
            print(f"[sync] custom_banners update error: {_cb_err}")

    if added_to_log:
        _save_updates(log)

    print(f"Sync complete — {updated} entries updated/added, {len(output) - updated} unchanged.")


if __name__ == "__main__":
    sync()
