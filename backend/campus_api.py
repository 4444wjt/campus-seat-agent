import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_STUDENT = "2023000001"
STUDENT_NAMES = {CURRENT_STUDENT: "张同学"}
SLOTS = ["08:00-10:00", "10:00-12:00", "14:00-16:00", "19:00-21:00"]
MAX_PER_DAY = 2
MAX_DAYS_AHEAD = 7
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

ROOMS = {
    "图书馆三楼A区": {"seats": 20, "window": set(range(1, 7)), "power": set(range(2, 21, 2))},
    "图书馆四楼B区": {"seats": 16, "window": set(range(1, 5)), "power": set(range(1, 9))},
    "教学楼201自习室": {"seats": 30, "window": set(), "power": set(range(1, 11))},
}


def _now() -> datetime:
    return datetime.now()


def _db_path() -> Path:
    path = Path(os.environ.get("CAMPUS_DB", "data/campus.db"))
    return path if path.is_absolute() else ROOT / path


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _result(ok: bool, message: str, data=None) -> dict:
    return {"ok": ok, "message": message, "data": data}


def init_db(reset: bool = False) -> None:
    from backend import seed

    conn = _connect()
    with conn:
        if reset:
            conn.execute("DROP TABLE IF EXISTS bookings")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                room TEXT NOT NULL,
                seat_no INTEGER NOT NULL,
                date TEXT NOT NULL,
                slot TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active')"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_active_seat
               ON bookings(room, seat_no, date, slot) WHERE status = 'active'"""
        )
        if conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0:
            seed.seed(conn, _now().date())
    conn.close()


def _resolve_room(room: str) -> tuple[str | None, str]:
    key = (room or "").strip()
    matches = [name for name in ROOMS if key and (key == name or key in name)]
    if len(matches) == 1:
        return matches[0], ""
    reason = "没有找到" if not matches else "匹配到多个"
    return None, f"{reason}与“{room}”对应的自习室，请从以下自习室中选择：{'、'.join(ROOMS)}。"


def _slot_start(date: str, slot: str) -> datetime:
    return datetime.strptime(f"{date} {slot[:5]}", "%Y-%m-%d %H:%M")


def _slot_end(date: str, slot: str) -> datetime:
    return datetime.strptime(f"{date} {slot[6:]}", "%Y-%m-%d %H:%M")


def _check_when(date: str, slot: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        return f"日期“{date}”格式不对，请使用 YYYY-MM-DD，例如 2026-11-04。"
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return f"日期“{date}”不存在，请检查后重新输入。"
    today = _now().date()
    if day < today:
        return f"{date} 已经是过去的日期，不能预约。可先查询今天起 {MAX_DAYS_AHEAD} 天内的空座。"
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        return f"{date} 超出可预约范围，仅可预约今天至 {today + timedelta(days=MAX_DAYS_AHEAD)} 之间的座位。"
    if slot not in SLOTS:
        return f"时段“{slot}”不在可选范围内，可选时段：{'、'.join(SLOTS)}。"
    if _slot_start(date, slot) <= _now():
        return f"{date} {slot} 已经开始，不能再预约。可先查询之后时段的空座。"
    return ""


def _seat_info(room: str, seat_no: int) -> dict:
    cfg = ROOMS[room]
    return {"seat_no": seat_no, "window": seat_no in cfg["window"], "power": seat_no in cfg["power"]}


def _describe(info: dict) -> str:
    tags = [t for t, on in (("靠窗", info["window"]), ("有插座", info["power"])) if on]
    return f"（{'、'.join(tags)}）" if tags else ""


def list_rooms() -> dict:
    rooms = []
    for name, cfg in ROOMS.items():
        window = f"{min(cfg['window'])}-{max(cfg['window'])} 号靠窗" if cfg["window"] else "无靠窗座位"
        power = f"{min(cfg['power'])}-{max(cfg['power'])} 号范围内" if cfg["power"] else "无"
        rooms.append({
            "room": name,
            "seats": cfg["seats"],
            "window_seats": sorted(cfg["window"]),
            "power_seats": sorted(cfg["power"]),
            "description": f"共 {cfg['seats']} 座，{window}，插座座位见 power_seats（{power}）",
        })
    return _result(True, f"共 {len(rooms)} 间自习室，每天分 {len(SLOTS)} 个时段：{'、'.join(SLOTS)}。",
                   {"rooms": rooms, "slots": SLOTS})


def query_free_seats(room: str, date: str, slot: str, feature: str | None = None) -> dict:
    name, err = _resolve_room(room)
    if not name:
        return _result(False, err)
    err = _check_when(date, slot)
    if err:
        return _result(False, err)
    if feature not in (None, "", "靠窗", "插座"):
        return _result(False, f"座位特征“{feature}”无法识别，可选“靠窗”或“插座”，也可不填。")
    conn = _connect()
    rows = conn.execute(
        "SELECT seat_no FROM bookings WHERE room=? AND date=? AND slot=? AND status='active'",
        (name, date, slot)).fetchall()
    conn.close()
    taken = {r["seat_no"] for r in rows}
    seats = [_seat_info(name, n) for n in range(1, ROOMS[name]["seats"] + 1) if n not in taken]
    if feature == "靠窗":
        seats = [s for s in seats if s["window"]]
    elif feature == "插座":
        seats = [s for s in seats if s["power"]]
    label = f"{name} {date} {slot}" + (f" {feature}" if feature else "")
    data = {"room": name, "date": date, "slot": slot, "free_seats": seats, "count": len(seats)}
    if not seats:
        return _result(True, f"{label} 暂无空位，可换个时段或自习室再查询。", data)
    return _result(True, f"{label} 共有 {len(seats)} 个空位。", data)


def book_seat(room: str, seat_no: int, date: str, slot: str, student_id: str = CURRENT_STUDENT) -> dict:
    name, err = _resolve_room(room)
    if not name:
        return _result(False, err)
    err = _check_when(date, slot)
    if err:
        return _result(False, err)
    total = ROOMS[name]["seats"]
    if not isinstance(seat_no, int) or not 1 <= seat_no <= total:
        return _result(False, f"{name} 的座位号范围是 1-{total}，“{seat_no}”无效。可先查询空座。")
    conn = _connect()
    try:
        taken = conn.execute(
            "SELECT 1 FROM bookings WHERE room=? AND seat_no=? AND date=? AND slot=? AND status='active'",
            (name, seat_no, date, slot)).fetchone()
        if taken:
            return _result(False, f"{name} {seat_no} 号座在 {date} {slot} 已被预约，可先查询空座再选择其他座位。")
        mine = conn.execute(
            "SELECT slot FROM bookings WHERE student_id=? AND date=? AND status='active'",
            (student_id, date)).fetchall()
        if any(r["slot"] == slot for r in mine):
            return _result(False, f"你在 {date} {slot} 已有一个预约，同一时段只能预约 1 个座位。可先查看我的预约。")
        if len(mine) >= MAX_PER_DAY:
            return _result(False, f"你在 {date} 已预约 {len(mine)} 个时段，每天最多 {MAX_PER_DAY} 个。可先取消其中一个再预约。")
        with conn:
            cur = conn.execute(
                "INSERT INTO bookings(student_id, room, seat_no, date, slot) VALUES (?,?,?,?,?)",
                (student_id, name, seat_no, date, slot))
    finally:
        conn.close()
    booking = {"booking_id": cur.lastrowid, "room": name, "seat_no": seat_no, "date": date, "slot": slot}
    return _result(True, f"预约成功：{name} {seat_no} 号座{_describe(_seat_info(name, seat_no))}，{date} {slot}。", booking)


def _booking_row(row: sqlite3.Row) -> dict:
    day = datetime.strptime(row["date"], "%Y-%m-%d")
    return {"booking_id": row["id"], "room": row["room"], "seat_no": row["seat_no"], "date": row["date"],
            "weekday": WEEKDAYS[day.weekday()], "slot": row["slot"]}


def my_bookings(student_id: str = CURRENT_STUDENT, include_past: bool = False) -> dict:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE student_id=? AND status='active' ORDER BY date, slot",
        (student_id,)).fetchall()
    conn.close()
    if not include_past:
        rows = [r for r in rows if _slot_end(r["date"], r["slot"]) > _now()]
    items = [_booking_row(r) for r in rows]
    scope = "全部" if include_past else "未结束的"
    if not items:
        return _result(True, f"暂无{scope}预约，可先查询空座后预约。", {"bookings": []})
    return _result(True, f"共有 {len(items)} 条{scope}预约。", {"bookings": items})


def cancel_booking(booking_id: int, student_id: str = CURRENT_STUDENT) -> dict:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if row is None:
            return _result(False, f"没有编号为 {booking_id} 的预约，可先查看我的预约。")
        if row["student_id"] != student_id:
            return _result(False, f"预约 {booking_id} 不属于你，只能取消本人的预约。")
        if row["status"] != "active":
            return _result(False, f"预约 {booking_id} 已经取消过了，无需重复操作。")
        if _slot_start(row["date"], row["slot"]) <= _now():
            return _result(False, f"预约 {booking_id}（{row['date']} {row['slot']}）已开始或已结束，不能取消。")
        with conn:
            conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    finally:
        conn.close()
    return _result(True, f"已取消预约：{row['room']} {row['seat_no']} 号座，{row['date']} {row['slot']}。",
                   _booking_row(row))


def export_weekly_report(note: str = "", student_id: str = CURRENT_STUDENT, out_dir: str = "workspace") -> dict:
    today = _now().date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE student_id=? AND status='active' AND date BETWEEN ? AND ? ORDER BY date, slot",
        (student_id, str(monday), str(sunday))).fetchall()
    conn.close()
    items = [_booking_row(r) for r in rows]
    name = STUDENT_NAMES.get(student_id, student_id)
    lines = [f"# 自习周报（{monday} ~ {sunday}）", "", f"学生：{name}", "", "## 统计", ""]
    if items:
        favorite, times = Counter(i["room"] for i in items).most_common(1)[0]
        lines += [f"- 预约次数：{len(items)} 次", f"- 总时长：{len(items) * 2} 小时",
                  f"- 最常去自习室：{favorite}（{times} 次）", "", "## 明细", "",
                  "| 日期 | 星期 | 时段 | 自习室 | 座位 |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {i['date']} | {i['weekday']} | {i['slot']} | {i['room']} | {i['seat_no']} 号 |" for i in items]
    else:
        lines += ["- 本周暂无有效预约。"]
    if note.strip():
        lines += ["", "## 建议", "", note.strip()]
    lines += ["", "数据为虚构样例", ""]
    directory = Path(out_dir)
    directory = directory if directory.is_absolute() else ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"weekly_report_{today}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return _result(True, f"周报已生成：{path}（{monday} ~ {sunday}，本周有效预约 {len(items)} 次）",
                   {"path": str(path), "week": f"{monday} ~ {sunday}", "count": len(items), "bookings": items})
