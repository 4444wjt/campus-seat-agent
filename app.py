import json
import uuid
from pathlib import Path

import streamlit as st
from langgraph.types import Command

from agent.seat_agent import build_agent, stream_turn
from backend import campus_api

WORKSPACE = Path(__file__).resolve().parent / "workspace"
SESSION_DIR = Path(__file__).resolve().parent / "data" / "sessions"
EXAMPLES = [
    "明天下午图书馆三楼还有靠窗的空位吗？",
    "帮我约明天 14:00-16:00 三楼一个靠窗空位",
    "我有哪些预约？把后天那个取消掉",
    "把我本周的预约整理成周报",
]


# ---------- 会话落盘：刷新页面 / 关掉浏览器再打开，对话还在 ----------
def _session_file(tid: str) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f"{tid}.json"


def load_messages(tid: str) -> list:
    path = _session_file(tid)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_messages(tid: str, messages: list) -> None:
    try:
        _session_file(tid).write_text(
            json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

st.set_page_config(page_title="校园自习室座位预约助手", page_icon="📚")
st.markdown("<style>[data-testid='stToolbar'], [data-testid='stStatusWidget'] {display: none;}</style>",
            unsafe_allow_html=True)


@st.cache_resource
def get_agent():
    campus_api.init_db()
    return build_agent()


def show_steps(steps: list[str]) -> None:
    for step in steps:
        st.write(step)


def run_turn(payload) -> None:
    steps: list[str] = []
    result = {"text": "", "interrupt": None}
    with st.chat_message("assistant"):
        status = st.status("执行过程", expanded=True)

        def tokens():
            for event in stream_turn(agent, payload, st.session_state["thread_id"]):
                kind = event[0]
                if kind == "token":
                    yield event[1]
                elif kind == "tool_call":
                    steps.append(f"调用工具 `{event[1]}`，参数：`{event[2]}`")
                    status.write(steps[-1])
                elif kind == "tool_result":
                    steps.append(f"`{event[1]}` 返回：{event[2][:200]}")
                    status.write(steps[-1])
                elif kind == "interrupt":
                    result["interrupt"] = event[1]
                elif kind == "done":
                    result["text"] = event[1]

        st.write_stream(tokens())
        status.update(label="执行过程", state="complete", expanded=False)
    if result["text"] or steps:
        st.session_state["messages"].append({"role": "assistant", "content": result["text"], "steps": steps})
    st.session_state["pending"] = result["interrupt"]
    save_messages(st.session_state["thread_id"], st.session_state["messages"])   # 落盘，刷新可恢复
    st.rerun()


# 会话 ID：优先读 URL 里的 ?t=，没有就新建并写回 URL（这样刷新能接上）
_qp = st.query_params
if not _qp.get("t"):
    _qp["t"] = uuid.uuid4().hex
_tid = _qp["t"]

# 换了会话（首次进入 / 刷新 / 打开带 t 的链接）→ 从磁盘把消息恢复回来
if st.session_state.get("thread_id") != _tid:
    st.session_state["thread_id"] = _tid
    st.session_state["messages"] = load_messages(_tid)
    st.session_state["pending"] = None

st.session_state.setdefault("messages", [])
st.session_state.setdefault("pending", None)

with st.sidebar:
    st.subheader("当前学生")
    st.write("张同学（2023000001，虚构）")
    if st.button("新会话", use_container_width=True):
        new_tid = uuid.uuid4().hex
        st.query_params["t"] = new_tid          # 先改 URL，避免 rerun 后被旧值覆盖
        st.session_state.update(messages=[], thread_id=new_tid, pending=None)
        st.rerun()
    st.subheader("示例问题")
    for i, example in enumerate(EXAMPLES):
        if st.button(example, key=f"example_{i}", use_container_width=True,
                     disabled=bool(st.session_state["pending"])):
            st.session_state["queued"] = example
    st.subheader("产出文件")
    files = sorted(WORKSPACE.glob("*.md"))
    for path in files:
        st.download_button(path.name, path.read_bytes(), file_name=path.name, key=f"dl_{path.name}")
    if not files:
        st.caption("暂无文件，可让助手生成周报。")

st.title("📚 校园自习室座位预约助手")
st.caption("用一句话查空座、预约、取消和生成周报；预约与取消需要你确认。")

try:
    agent = get_agent()
except RuntimeError as e:
    st.warning(str(e))
    st.stop()

for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        if message.get("steps"):
            with st.expander("执行过程"):
                show_steps(message["steps"])
        st.write(message["content"])

pending = st.session_state["pending"]
if pending:
    with st.chat_message("assistant"):
        st.warning("请确认以下操作：\n\n" + "\n\n".join(f"- {a['description']}" for a in pending))
        approve = st.button("确认执行", type="primary")
        reject = st.button("取消操作")
    if approve or reject:
        decision = {"type": "approve"} if approve else {"type": "reject", "message": "用户取消了该操作"}
        st.session_state["pending"] = None
        run_turn(Command(resume={"decisions": [decision] * len(pending)}))

prompt = st.chat_input("例如：帮我约明天 14:00-16:00 三楼一个靠窗空位", disabled=bool(pending))
prompt = prompt or st.session_state.pop("queued", None)
if prompt:
    st.session_state["messages"].append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)
    run_turn(prompt)

st.divider()
st.caption("数据为虚构样例，预约规则以学校官方通知为准。")
