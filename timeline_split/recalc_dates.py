"""
Recalculates estimated global dates for all unconfirmed entries in
banners.json and pvp.json using the time factor formula:

    global_date = anchor_global + (jp_date - anchor_jp) / time_factor

Edit config.json to change the time_factor or anchor dates, then run:
    python timeline_split/recalc_dates.py
"""

import json
from datetime import datetime, timedelta, date, timezone
from pathlib import Path

DIR = Path(__file__).parent


def load_config():
    return json.loads((DIR / "config.json").read_text(encoding="utf-8"))


def parse_dt(s):
    if not s:
        return None
    s = s.strip()
    if "T" in s or "Z" in s:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def make_anchor(cfg_anchor):
    jp = datetime.fromisoformat(cfg_anchor["jp_date"]).replace(tzinfo=timezone.utc)
    gl = datetime.fromisoformat(cfg_anchor["global_date"]).replace(tzinfo=timezone.utc)
    return jp, gl


def jp_to_global_date(jp_dt, anchor_jp, anchor_gl, time_factor):
    delta_days = (jp_dt - anchor_jp).total_seconds() / 86400
    result = anchor_gl + timedelta(days=delta_days / time_factor)
    return result.date()


def recalc_banners(time_factor, anchor_jp, anchor_gl):
    path = DIR / "banners.json"
    banners = json.loads(path.read_text(encoding="utf-8"))
    updated = 0
    for b in banners:
        if b.get("is_confirmed") or not b.get("jp_release_date"):
            continue
        jp_dt = parse_dt(b["jp_release_date"])
        gl_date = jp_to_global_date(jp_dt, anchor_jp, anchor_gl, time_factor)
        b["start_date"] = f"{gl_date}T22:00:00Z"
        if b.get("banner_duration_days"):
            b["end_date"] = f"{gl_date + timedelta(days=b['banner_duration_days'])}T22:00:00Z"
        updated += 1
    path.write_text(json.dumps(banners, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"banners.json: {updated} entries updated")


def recalc_pvp(time_factor, anchor_jp, anchor_gl):
    path = DIR / "pvp.json"
    pvp = json.loads(path.read_text(encoding="utf-8"))
    updated = 0
    for p in pvp:
        if p.get("is_confirmed"):
            continue
        jp_dt = parse_dt(p.get("jp_release_date"))
        if not jp_dt and p.get("jp_start_date"):
            jp_dt = parse_dt(p["jp_start_date"])
            p["jp_release_date"] = f"{jp_dt.date()}T03:00:00Z"
            if p.get("jp_end_date") and not p.get("banner_duration_days"):
                p["banner_duration_days"] = (parse_dt(p["jp_end_date"]) - jp_dt).days
        if not jp_dt:
            continue
        gl_date = jp_to_global_date(jp_dt, anchor_jp, anchor_gl, time_factor)
        p["start_date"] = f"{gl_date}T22:00:00Z"
        if p.get("banner_duration_days"):
            p["end_date"] = f"{gl_date + timedelta(days=p['banner_duration_days'])}T22:00:00Z"
        updated += 1
    path.write_text(json.dumps(pvp, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"pvp.json:     {updated} entries updated")


def recalc_step_ups():
    path = DIR / "banners.json"
    banners = json.loads(path.read_text(encoding="utf-8"))
    banner_map = {b["banner_id"]: b for b in banners}
    updated = 0
    for b in banners:
        if b.get("type") != "step_up" or not b.get("tied_to_banner_id"):
            continue
        source = banner_map.get(b["tied_to_banner_id"])
        if source:
            if source.get("start_date"):
                b["start_date"] = source["start_date"]
            if source.get("end_date"):
                b["end_date"] = source["end_date"]
            updated += 1
    path.write_text(json.dumps(banners, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"step_ups:           {updated} entries updated")


def recalc_packs(time_factor, anchor_jp, anchor_gl):
    banners_path = DIR / "banners.json"
    packs_path   = DIR / "packs.json"
    banners  = json.loads(banners_path.read_text(encoding="utf-8"))
    packs    = json.loads(packs_path.read_text(encoding="utf-8"))
    # Step-up sync
    step_up_map = {}
    for b in banners:
        if b.get("type") != "step_up" or not b.get("start_date"):
            continue
        key = b["banner_name"].replace(" Step Up", "").strip()
        step_up_map[key] = b["start_date"][:10]
    step_updated = 0
    jp_updated = 0
    for e in packs.get("events", []):
        if e.get("step_up_banner"):
            start = step_up_map.get(e["step_up_banner"])
            if start:
                e["start"] = start
                step_updated += 1
        elif e.get("jp_start"):
            jp_dt = datetime.fromisoformat(e["jp_start"]).replace(tzinfo=timezone.utc)
            gl_date = jp_to_global_date(jp_dt, anchor_jp, anchor_gl, time_factor)
            e["start"] = str(gl_date)
            jp_updated += 1
    packs_path.write_text(json.dumps(packs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"packs.json:         {step_updated} step-ups synced, {jp_updated} jp dates converted")


def recalc_anniversaries():
    banners_path = DIR / "banners.json"
    ann_path = DIR / "anniversaries.json"
    banners = json.loads(banners_path.read_text(encoding="utf-8"))
    anniversaries = json.loads(ann_path.read_text(encoding="utf-8"))
    banner_map = {b["banner_id"]: b for b in banners}
    updated = 0
    for a in anniversaries:
        bid = a.get("tied_to_banner_id")
        if not bid:
            continue
        b = banner_map.get(bid)
        if b and b.get("start_date"):
            a["start_date"] = b["start_date"]
            updated += 1
    ann_path.write_text(json.dumps(anniversaries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"anniversaries.json: {updated} entries updated")


if __name__ == "__main__":
    cfg = load_config()
    time_factor = cfg["time_factor"]
    b_anchor_jp, b_anchor_gl = make_anchor(cfg["banners_anchor"])
    p_anchor_jp, p_anchor_gl = make_anchor(cfg["pvp_anchor"])

    print(f"Time factor:     {time_factor}")
    print(f"Banners anchor:  jp={b_anchor_jp.date()}  global={b_anchor_gl.date()}")
    print(f"PvP anchor:      jp={p_anchor_jp.date()}  global={p_anchor_gl.date()}")
    print()

    recalc_banners(time_factor, b_anchor_jp, b_anchor_gl)
    recalc_step_ups()
    recalc_packs(time_factor, b_anchor_jp, b_anchor_gl)
    recalc_pvp(time_factor, p_anchor_jp, p_anchor_gl)
    recalc_anniversaries()
