import json
from pathlib import Path

from langchain_core.tools import tool

from backend import campus_api as api

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


@tool
def list_rooms() -> str:
    """列出所有自习室、座位数、靠窗/插座情况和每天可预约的时段。
    用户询问有哪些自习室、有哪些时段，或不确定自习室名称时使用。无参数。"""
    return _json(api.list_rooms())


@tool
def query_free_seats(room: str, date: str, slot: str, feature: str | None = None) -> str:
    """查询某自习室某天某时段的空座位。预约前必须先用它确认座位空闲。
    参数：room 自习室名称，可用简称如“三楼”；date 日期，格式 YYYY-MM-DD；
    slot 时段，如 14:00-16:00；feature 可选，“靠窗”或“插座”，不限制则不填。"""
    return _json(api.query_free_seats(room, date, slot, feature))


@tool
def book_seat(room: str, seat_no: int, date: str, slot: str) -> str:
    """为当前学生预约一个座位。应先查询空座再调用；调用后系统会自动弹出确认卡片，无需在对话中询问用户。
    参数：room 自习室名称；seat_no 座位号（整数）；date 日期，格式 YYYY-MM-DD；slot 时段，如 14:00-16:00。"""
    return _json(api.book_seat(room, seat_no, date, slot))


@tool
def my_bookings(include_past: bool = False) -> str:
    """查看当前学生的预约记录，返回预约编号、自习室、座位、日期和时段。
    取消预约前需要先用它找到预约编号；写周报时用 include_past=True 取得含已过去的全部预约。
    参数：include_past 是否包含已结束的预约，默认 False。"""
    return _json(api.my_bookings(include_past=include_past))


@tool
def cancel_booking(booking_id: int) -> str:
    """取消当前学生的一条预约，只能取消未开始的预约。调用后系统会自动弹出确认卡片，无需在对话中询问用户。
    参数：booking_id 预约编号，来自 my_bookings 的结果。"""
    return _json(api.cancel_booking(booking_id))


@tool
def export_weekly_report(note: str = "") -> str:
    """生成本周自习周报（Markdown 文件，保存到 workspace 目录）并返回文件路径。
    参数：note 学习安排建议，会写入周报末尾的“建议”部分，没有则留空。"""
    return _json(api.export_weekly_report(note))


@tool
def read_skill(name: str) -> str:
    """读取一个 Skill 的完整操作说明及其附带模板。当用户需求匹配系统提示词中列出的某个 Skill 时，先调用它再按说明执行。
    参数：name Skill 名称，如 weekly-report。"""
    path = (SKILLS_DIR / name / "SKILL.md").resolve()
    if SKILLS_DIR.resolve() not in path.parents or not path.is_file():
        return f"没有名为“{name}”的 Skill。"
    files = sorted(path.parent.glob("*.md"), key=lambda p: p.name != "SKILL.md")
    return "\n\n".join(f"## 文件：{p.name}\n\n{p.read_text(encoding='utf-8')}" for p in files)


TOOLS = [list_rooms, query_free_seats, book_seat, my_bookings, cancel_booking, export_weekly_report, read_skill]
