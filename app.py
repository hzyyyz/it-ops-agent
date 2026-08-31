import time
import streamlit as st
from agent.react_agent import ReactAgent

# 页面配置
st.set_page_config(
    page_title="IT运维智能助手",
    page_icon="",
    layout="centered",
    initial_sidebar_state="expanded",
)

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
    st.markdown('<div class="main-header">IT 运维助手</div>', unsafe_allow_html=True)
    st.caption("企业设备管理与故障排查")

    st.divider()

    st.markdown('<div class="sidebar-section"><h3>快捷操作</h3></div>', unsafe_allow_html=True)
    if st.button("清除对话", use_container_width=True):
        st.session_state["message"] = [
            {"role": "assistant",
             "content": "你好，我是IT运维智能助手，可以帮你排查设备故障、查询资产信息、生成设备健康度报告，请问有什么需要？"}
        ]
        st.rerun()

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
        if st.button(q, use_container_width=True):
            st.session_state["_quick_question"] = q
            st.rerun()

    st.divider()

    st.markdown('<div class="sidebar-section"><h3>关于</h3></div>', unsafe_allow_html=True)
    st.caption("基于 LangChain/LangGraph 构建的 ReAct Agent，集成 RAG 检索增强生成。")
    st.caption("v1.0 | DeepSeek")

# 主内容区
st.markdown('<p class="main-header">IT运维智能助手</p>', unsafe_allow_html=True)
st.caption("排查设备故障 · 查询资产信息 · 生成健康度报告 · 安全策略咨询")

# 初始化 session state
if "message" not in st.session_state:
    st.session_state["message"] = [
        {"role": "assistant",
         "content": "你好，我是IT运维智能助手，可以帮你排查设备故障、查询资产信息、生成设备健康度报告，请问有什么需要？"}
    ]

if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()

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
    st.session_state["message"].append({"role": "user", "content": prompt})

    response_messages = []
    with st.spinner("分析处理中..."):
        try:
            history = st.session_state["message"][:-1]
            res_stream = st.session_state["agent"].execute_stream(prompt, history)

            def capture(generator, cache_list):
                for chunk in generator:
                    cache_list.append(chunk)
                    for char in chunk:
                        time.sleep(0.01)
                        yield char

            with st.chat_message("assistant"):
                st.write_stream(capture(res_stream, response_messages))
            st.session_state["message"].append({"role": "assistant", "content": "".join(response_messages)})

        except Exception as e:
            st.error(f"处理请求时出现异常：{str(e)}")
            st.caption("请刷新页面后重试，或联系管理员。")
