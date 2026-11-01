TOMORROW = "2026-11-05"
SLOT = "14:00-16:00"


def test_fuzzy_room_match(api):
    result = api.query_free_seats("三楼", TOMORROW, SLOT)
    assert result["ok"] and result["data"]["room"] == "图书馆三楼A区"


def test_room_not_found_or_ambiguous_lists_all(api):
    for key in ("五楼", "图书馆"):
        result = api.query_free_seats(key, TOMORROW, SLOT)
        assert not result["ok"]
        assert "图书馆三楼A区" in result["message"] and "教学楼201自习室" in result["message"]


def test_free_seats_feature_filter(api):
    window = api.query_free_seats("三楼", TOMORROW, SLOT, "靠窗")["data"]["free_seats"]
    assert window and all(s["window"] for s in window)
    power = api.query_free_seats("三楼", TOMORROW, SLOT, "插座")["data"]["free_seats"]
    assert power and all(s["seat_no"] % 2 == 0 for s in power)


def test_book_success_and_listed(api):
    seat = api.query_free_seats("三楼", TOMORROW, SLOT, "靠窗")["data"]["free_seats"][0]["seat_no"]
    result = api.book_seat("三楼", seat, TOMORROW, SLOT)
    assert result["ok"] and "预约成功" in result["message"]
    ids = [b["booking_id"] for b in api.my_bookings()["data"]["bookings"]]
    assert result["data"]["booking_id"] in ids
    left = api.query_free_seats("三楼", TOMORROW, SLOT)["data"]["free_seats"]
    assert all(s["seat_no"] != seat for s in left)


def test_duplicate_seat_conflict(api):
    seat = api.query_free_seats("三楼", TOMORROW, SLOT)["data"]["free_seats"][0]["seat_no"]
    assert api.book_seat("三楼", seat, TOMORROW, SLOT, "2023000002")["ok"]
    result = api.book_seat("三楼", seat, TOMORROW, SLOT)
    assert not result["ok"] and "已被预约" in result["message"]


def test_same_slot_limit_and_daily_limit(api):
    free = api.query_free_seats("三楼", TOMORROW, SLOT)["data"]["free_seats"]
    assert api.book_seat("三楼", free[0]["seat_no"], TOMORROW, SLOT)["ok"]
    same_slot = api.book_seat("三楼", free[1]["seat_no"], TOMORROW, SLOT)
    assert not same_slot["ok"] and "同一时段" in same_slot["message"]
    over_limit = api.book_seat("三楼", free[1]["seat_no"], TOMORROW, "08:00-10:00")
    assert not over_limit["ok"] and "最多" in over_limit["message"]


def test_date_out_of_range(api):
    assert "过去" in api.book_seat("三楼", 1, "2026-11-03", SLOT)["message"]
    assert "超出" in api.book_seat("三楼", 1, "2026-11-12", SLOT)["message"]
    assert "格式" in api.book_seat("三楼", 1, "明天", SLOT)["message"]


def test_started_slot_and_seat_range(api):
    started = api.book_seat("三楼", 1, "2026-11-04", "10:00-12:00")
    assert not started["ok"] and "已经开始" in started["message"]
    assert "座位号范围" in api.book_seat("三楼", 99, TOMORROW, SLOT)["message"]


def test_cancel_rules(api):
    bookings = api.my_bookings()["data"]["bookings"]
    target = bookings[0]["booking_id"]
    assert "不属于你" in api.cancel_booking(target, "2023000002")["message"]
    assert api.cancel_booking(target)["ok"]
    assert "已经取消" in api.cancel_booking(target)["message"]
    past = [b for b in api.my_bookings(include_past=True)["data"]["bookings"] if b["date"] < "2026-11-04"][0]
    assert "不能取消" in api.cancel_booking(past["booking_id"])["message"]


def test_weekly_report_file(api, tmp_path):
    result = api.export_weekly_report("多去四楼复习", out_dir=str(tmp_path / "out"))
    assert result["ok"]
    path = result["data"]["path"]
    text = open(path, encoding="utf-8").read()
    assert "图书馆四楼B区" in text and "## 建议" in text and "多去四楼复习" in text
    assert text.rstrip().endswith("数据为虚构样例")
    assert path.endswith("weekly_report_2026-11-04.md")
