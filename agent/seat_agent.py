import logging
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelRequest, dynamic_prompt, wrap_tool_call
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent.tools import SKILLS_DIR, TOOLS
from backend import campus_api as api

ROOT = Path(__file__).resolve().parent.parent
PROMPT_FILE = ROOT / "prompts" / "system_prompt.txt"
DEFAULT_BASE_URL = "https://api.deepseek.com"

load_dotenv(ROOT / ".env")
logger = logging.getLogger("seat_agent")


def build_model() -> ChatOpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未配置 OPENAI_API_KEY：请复制 .env.example 为 .env，填入模型平台（DeepSeek 或阿里百炼）的 API Key 后重启。")
    return ChatOpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
                      model=os.getenv("LLM_MODEL", "deepseek-v4-pro"), streaming=True)


def _skills_text() -> str:
    lines = []
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        head = path.read_text(encoding="utf-8").split("---")[1]
        meta = dict(line.split(":", 1) for line in head.strip().splitlines())
        lines.append(f"- {meta['name'].strip()}：{meta['description'].strip()}")
    return "\n".join(lines)


@dynamic_prompt
def build_prompt(request: ModelRequest) -> str:
    now = api._now()
    monday = now.date() - timedelta(days=now.weekday())
    return (PROMPT_FILE.read_text(encoding="utf-8")
            + f"\n\n今天是 {now:%Y-%m-%d} {api.WEEKDAYS[now.weekday()]}，本周为 {monday} 至 {monday + timedelta(days=6)}，"
            + f"当前学生：张同学（{api.CURRENT_STUDENT}）。"
            + f"\n\n可用 Skills（需要时先用 read_skill 读取说明）：\n{_skills_text()}")


@wrap_tool_call
def log_tool(request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]):
    name = request.tool_call["name"]
    logger.info("执行工具 %s 参数 %s", name, request.tool_call["args"])
    try:
        return handler(request)
    except Exception as e:
        logger.error("工具 %s 调用失败：%s", name, e)
        raise


def _book_description(tool_call: dict, state, runtime) -> str:
    a = tool_call["args"]
    room = api._resolve_room(a["room"])[0] or a["room"]
    return f"即将预约：{room} {a['seat_no']} 号座，{a['date']} {a['slot']}"


def _cancel_description(tool_call: dict, state, runtime) -> str:
    booking_id = tool_call["args"]["booking_id"]
    items = api.my_bookings(include_past=True)["data"]["bookings"]
    b = next((i for i in items if i["booking_id"] == booking_id), None)
    if b is None:
        return f"即将取消预约编号 {booking_id}"
    return f"即将取消预约：{b['room']} {b['seat_no']} 号座，{b['date']} {b['slot']}"


def build_agent(model=None, db_path: str | Path | None = None):
    path = Path(db_path) if db_path else ROOT / "data" / "checkpoints.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    confirm = HumanInTheLoopMiddleware(interrupt_on={
        "book_seat": {"allowed_decisions": ["approve", "reject"], "description": _book_description},
        "cancel_booking": {"allowed_decisions": ["approve", "reject"], "description": _cancel_description},
    })
    return create_agent(model=model or build_model(), tools=TOOLS, checkpointer=saver,
                        middleware=[build_prompt, log_tool, confirm])


def stream_turn(agent, payload, thread_id: str):
    """payload 为用户文本或 Command；产出 token / tool_call / tool_result / interrupt / done 事件。"""
    if isinstance(payload, str):
        payload = {"messages": [{"role": "user", "content": payload}]}
    config = {"configurable": {"thread_id": thread_id}}
    seen_calls = set()
    text = ""
    for mode, chunk in agent.stream(payload, config, stream_mode=["updates", "messages"]):
        if mode == "messages":
            message, _ = chunk
            if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content:
                text += message.content
                yield ("token", message.content)
            continue
        if "__interrupt__" in chunk:
            yield ("interrupt", chunk["__interrupt__"][0].value["action_requests"])
            continue
        for update in chunk.values():
            for message in (update or {}).get("messages", []):
                if isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        if call["id"] not in seen_calls:
                            seen_calls.add(call["id"])
                            yield ("tool_call", call["name"], call["args"])
                elif isinstance(message, ToolMessage):
                    yield ("tool_result", message.name, message.content)
    yield ("done", text)
