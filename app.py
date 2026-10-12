from pathlib import Path
import os
from secrets import compare_digest

import streamlit as st
from dotenv import load_dotenv

from frontend.chat_client import ChatAPIError, request_chat_stream, list_sessions, get_session, delete_session

load_dotenv(Path(__file__).with_name(".env"))

WELCOME = {"role": "assistant", "content": "你好，我是IT运维智能助手，可以帮你排查设备故障、查询资产信息、生成设备健康度报告，请问有什么需要？"}
st.session_state.setdefault("session_id", None)
st.session_state.setdefault("message", [WELCOME.copy()])
st.session_state.setdefault("session_offset", 0)

# 页面配置
st.set_page_config(
    page_title="IT运维智能助手",
    page_icon="",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.session_state.setdefault("admin_authenticated", False)
expected_admin_token = os.getenv("AGENT_ADMIN_TOKEN", "")
if len(expected_admin_token) < 32 or expected_admin_token.startswith("replace-with-"):
    st.error("请先在环境变量或 .env 中配置至少 32 个随机字符的 AGENT_ADMIN_TOKEN。")
    st.stop()
if not st.session_state["admin_authenticated"]:
    st.title("进入 IT 运维助手")
    with st.form("admin_login"):
        entered_token = st.text_input("管理员口令", type="password", key="admin_password")
        submitted = st.form_submit_button("进入工作台")
    if submitted:
        if compare_digest(entered_token, expected_admin_token):
            st.session_state["admin_authenticated"] = True
            st.rerun()
        else:
            st.error("管理员口令无效。")
    st.stop()
st.session_state.pop("admin_password", None)

# 自定义样式
st.markdown("""
<style>
    .main-header {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1a73e8;
        padding-bottom: 0.5rem;
    }
    .stChatMessage { border-radius: 12px; }
    .sidebar-section { margin-bottom: 1.5rem; }
    .sidebar-section h3 { font-size: 0.9rem; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }
    .quick-btn {
        display: inline-block;
        padding: 0.4rem 0.8rem;
        margin: 0.2rem;
        border: 1px solid #ddd;
        border-radius: 20px;
        font-size: 0.8rem;
        cursor: pointer;
        transition: all 0.2s;
    }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# 侧边栏
with st.sidebar:
    if st.button("退出工作台"):
        st.session_state["admin_authenticated"] = False
        st.rerun()
    st.markdown('<div class="main-header">IT 运维助手</div>', unsafe_allow_html=True)
    st.caption("企业设备管理与故障排查")

    st.divider()

    st.markdown('<div class="sidebar-section"><h3>快捷操作</h3></div>', unsafe_allow_html=True)
    if st.button("新建会话"):
        st.session_state["session_id"] = None
        st.session_state["message"] = [WELCOME.copy()]
        st.session_state.pop("_quick_question", None)
        st.rerun()

    st.caption("历史会话")
    try:
        sessions = list_sessions(offset=st.session_state["session_offset"])
        for session in sessions:
            label = session["title"]
            if session["id"] == st.session_state["session_id"]:
                label = "当前 · " + label
            if st.button(label, key=f"session_{session['id']}"):
                st.session_state["session_id"] = session["id"]
                st.session_state["message"] = []
                st.session_state.pop("_quick_question", None)
                st.rerun()
        if not sessions:
            st.caption("暂无会话")
        if st.button("上一页", disabled=st.session_state["session_offset"] == 0):
            st.session_state["session_offset"] = max(0, st.session_state["session_offset"] - 20)
            st.rerun()
        if st.button("下一页", disabled=len(sessions) < 20):
            st.session_state["session_offset"] += 20
            st.rerun()
    except ChatAPIError as exc:
        st.warning(str(exc))

    current_id = st.session_state["session_id"]
    if current_id:
        confirmed = st.checkbox("确认删除此会话及全部消息", key=f"delete_confirm_{current_id}")
        if st.button("删除当前会话", disabled=not confirmed):
            try:
                delete_session(current_id)
                st.session_state["session_id"] = None
                st.session_state["message"] = [WELCOME.copy()]
                st.session_state["session_offset"] = 0
                st.session_state.pop("_quick_question", None)
                st.rerun()
            except ChatAPIError as exc:
                st.error(str(exc))

    st.divider()

    st.markdown('<div class="sidebar-section"><h3>常见问题</h3></div>', unsafe_allow_html=True)
    quick_questions = [
        "电脑蓝屏怎么排查",
        "帮我生成设备健康度报告",
        "办公电脑运行卡顿怎么办",
        "企业网络安全策略有哪些",
        "员工设备采购有什么建议",
    ]
    for q in quick_questions:
        if st.button(q):
            st.session_state["_quick_question"] = q
            st.rerun()

    st.divider()

    st.markdown('<div class="sidebar-section"><h3>关于</h3></div>', unsafe_allow_html=True)
    st.caption("基于 LangChain/LangGraph 构建的 ReAct Agent，集成 RAG 检索增强生成。")
    st.caption("v3.0 | 实时回答 · MySQL 历史会话")

# 主内容区
st.markdown('<p class="main-header">IT运维智能助手</p>', unsafe_allow_html=True)
st.caption("排查设备故障 · 查询资产信息 · 生成健康度报告 · 安全策略咨询")

# 切换会话和页面重跑时都以数据库中的历史为准。
if st.session_state["session_id"]:
    try:
        detail = get_session(st.session_state["session_id"])
        st.session_state["message"] = [
            {"role": item["role"], "content": item["content"]} for item in detail["messages"]
        ]
    except ChatAPIError as exc:
        st.error(str(exc))
        st.caption("可以重试或点击新建会话。")
        st.stop()

# 渲染历史消息
for message in st.session_state["message"]:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 处理快捷提问与聊天输入
chat_prompt = st.chat_input("请输入你的问题...")
if "_quick_question" in st.session_state:
    prompt = st.session_state.pop("_quick_question")
else:
    prompt = chat_prompt

if prompt:
    st.chat_message("user").write(prompt)
    with st.chat_message("assistant"):
        try:
            stream = request_chat_stream(prompt, st.session_state["session_id"])
            answer = st.write_stream(stream)
            st.session_state["session_id"] = stream.session_id
            st.session_state["message"].extend([
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ])
            st.session_state["session_offset"] = 0
            st.rerun()

        except ChatAPIError as exc:
            st.error(str(exc))
            st.caption("请先刷新会话核对历史，再决定是否重新发送。")
