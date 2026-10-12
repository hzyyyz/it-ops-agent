from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.chat_client import ChatAPIError
import pytest


APP = str(Path(__file__).resolve().parents[1] / "app.py")
SID = "2f37f9c7-233b-4f09-a46f-000000000001"


@pytest.fixture
def history_backend(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "test-admin-token-12345678901234567890")
    conversations = {}
    monkeypatch.setattr("frontend.chat_client.list_sessions", lambda **kwargs: list(conversations.values()))
    monkeypatch.setattr("frontend.chat_client.get_session", lambda sid: conversations[sid])
    monkeypatch.setattr("frontend.chat_client.delete_session", lambda sid: conversations.pop(sid))
    return conversations


def _logged_in_app():
    app = AppTest.from_file(APP).run(timeout=15)
    app.text_input(key="admin_password").set_value("test-admin-token-12345678901234567890").run()
    next(button for button in app.button if button.label == "进入工作台").click().run()
    return app


def test_streamlit_requires_admin_password(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "test-admin-token-12345678901234567890")
    app = AppTest.from_file(APP).run(timeout=15)
    assert not app.chat_input
    app.text_input(key="admin_password").set_value("wrong-password").run()
    next(button for button in app.button if button.label == "进入工作台").click().run()
    assert not app.chat_input
    assert app.error


def test_chat_history_and_clear(monkeypatch, history_backend):
    calls = []

    def reply(message, session_id=None):
        calls.append((message, session_id))

        class Stream:
            session_id = SID

            def __iter__(self):
                yield "设备运行"
                yield "正常"
                conversation = history_backend.setdefault(SID, {"id": SID, "title": "检查设备", "messages": []})
                conversation["messages"].extend([
                    {"role": "user", "content": message}, {"role": "assistant", "content": "设备运行正常"}])

        return Stream()

    monkeypatch.setattr("frontend.chat_client.request_chat_stream", reply, raising=False)
    app = _logged_in_app()
    assert not app.exception
    app.chat_input[0].set_value("检查设备").run()
    assert not app.exception
    assert app.session_state["message"][-1]["content"] == "设备运行正常"
    app.chat_input[0].set_value("详细解释").run()
    assert calls == [("检查设备", None), ("详细解释", SID)]
    next(button for button in app.button if button.label == "新建会话").click().run()
    assert len(app.session_state["message"]) == 1
    assert app.session_state["session_id"] is None
    assert len(history_backend[SID]["messages"]) == 4
    # Re-open the persisted conversation, then explicitly delete it.
    app.button(key=f"session_{SID}").click().run()
    assert len(app.session_state["message"]) == 4
    app.checkbox[0].check().run()
    next(button for button in app.button if button.label == "删除当前会话").click().run()
    assert SID not in history_backend
    assert app.session_state["session_id"] is None
    assert not app.exception


def test_backend_failure_does_not_pollute_history(monkeypatch, history_backend):
    def fail(*args):
        raise ChatAPIError("无法连接后端")

    monkeypatch.setattr("frontend.chat_client.request_chat_stream", fail, raising=False)
    app = _logged_in_app()
    app.chat_input[0].set_value("检查设备").run()
    assert not app.exception
    assert app.error[0].value == "无法连接后端"
    assert len(app.session_state["message"]) == 1


def test_pending_quick_question_does_not_move_to_another_session(monkeypatch, history_backend):
    other_id = "2f37f9c7-233b-4f09-a46f-000000000002"
    history_backend.update({
        SID: {"id": SID, "title": "旧会话", "messages": []},
        other_id: {"id": other_id, "title": "另一个会话", "messages": []},
    })
    calls = []

    def get_detail(sid):
        if sid == SID:
            raise ChatAPIError("暂时不可用", 503)
        return history_backend[sid]

    def unexpected_chat(*args):
        calls.append(args)
        raise ChatAPIError("不应该发送")

    monkeypatch.setattr("frontend.chat_client.get_session", get_detail)
    monkeypatch.setattr("frontend.chat_client.request_chat_stream", unexpected_chat, raising=False)
    app = _logged_in_app()
    app.button(key=f"session_{SID}").click().run()
    next(button for button in app.button if button.label == "电脑蓝屏怎么排查").click().run()
    assert app.session_state["_quick_question"]
    app.button(key=f"session_{other_id}").click().run()
    assert not app.exception
    assert calls == []
