import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.types import Command

from agent.seat_agent import build_agent, stream_turn
from backend import campus_api

TOMORROW = "2026-11-05"
SLOT = "14:00-16:00"


class FakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}"}])


def make_agent(tmp_path, *messages):
    return build_agent(FakeModel(responses=list(messages)), db_path=tmp_path / "checkpoints.db")


def events(agent, payload, thread="t1"):
    return list(stream_turn(agent, payload, thread))


def active_count():
    return len(campus_api.my_bookings(include_past=True)["data"]["bookings"])


def test_book_approve(api, tmp_path):
    agent = make_agent(tmp_path,
                       call("book_seat", {"room": "三楼", "seat_no": 3, "date": TOMORROW, "slot": SLOT}),
                       AIMessage(content="已为你预约。"))
    before = active_count()
    first = events(agent, "帮我约明天下午三楼 3 号")
    assert [e[0] for e in first] == ["tool_call", "interrupt", "done"]
    assert "即将预约：图书馆三楼A区 3 号座" in first[-2][1][0]["description"]
    assert active_count() == before

    second = events(agent, Command(resume={"decisions": [{"type": "approve"}]}))
    kinds = [e[0] for e in second]
    assert "tool_result" in kinds and kinds[-1] == "done"
    assert json.loads(next(e for e in second if e[0] == "tool_result")[2])["ok"]
    assert second[-1][1] == "已为你预约。"
    assert active_count() == before + 1


def test_cancel_reject(api, tmp_path):
    booking = api.my_bookings()["data"]["bookings"][0]
    agent = make_agent(tmp_path,
                       call("cancel_booking", {"booking_id": booking["booking_id"]}),
                       AIMessage(content="好的，已保留预约。"))
    before = active_count()
    first = events(agent, "取消我最近的预约")
    assert first[-2][0] == "interrupt"
    assert "即将取消预约" in first[-2][1][0]["description"]

    second = events(agent, Command(resume={"decisions": [{"type": "reject", "message": "用户取消了该操作"}]}))
    assert second[-1] == ("done", "好的，已保留预约。")
    assert active_count() == before
