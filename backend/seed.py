import sqlite3
from datetime import date, timedelta

from backend.campus_api import CURRENT_STUDENT, ROOMS, SLOTS


def seed(conn: sqlite3.Connection, today: date) -> None:
    mine = [
        (today - timedelta(days=2), "10:00-12:00", "图书馆三楼A区", 8),
        (today + timedelta(days=1), "19:00-21:00", "图书馆四楼B区", 5),
        (today + timedelta(days=2), "10:00-12:00", "教学楼201自习室", 12),
    ]
    rows = [(CURRENT_STUDENT, room, seat, str(day), slot) for day, slot, room, seat in mine]
    tomorrow = str(today + timedelta(days=1))
    for r_idx, (room, cfg) in enumerate(ROOMS.items()):
        for offset in range(8):
            day = str(today + timedelta(days=offset))
            for s_idx, slot in enumerate(SLOTS):
                for seat in range(1, cfg["seats"] + 1):
                    if (seat + offset * 3 + s_idx * 5 + r_idx) % 3 != 0:
                        continue
                    if room == "图书馆三楼A区" and day == tomorrow and slot == "14:00-16:00" and seat <= 6:
                        continue
                    rows.append((f"2023{100000 + seat:06d}", room, seat, day, slot))
    conn.executemany(
        "INSERT OR IGNORE INTO bookings(student_id, room, seat_no, date, slot) VALUES (?,?,?,?,?)", rows)
