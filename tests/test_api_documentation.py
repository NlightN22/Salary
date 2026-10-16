from html.parser import HTMLParser
import pytest
import shlex
from urllib.parse import urlsplit

from starlette.routing import Match

from salary_web.app import app
from salary_web.auth import make_session_token
from tests.test_extended_boundaries import scoped_client  # noqa: F401


class Examples(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = {}
        self.targets = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "code" and attrs.get("id", "").startswith("copy-"):
            self.current = attrs["id"]
            self.blocks[self.current] = ""
        if "data-copy-target" in attrs:
            self.targets.append(attrs["data-copy-target"])

    def handle_endtag(self, tag):
        if tag == "code":
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.blocks[self.current] += data


@pytest.mark.parametrize("cookie", [None, "invalid-session"])
def test_documentation_redirects_to_login_without_valid_session(scoped_client, cookie):
    client, *_ = scoped_client
    if cookie:
        client.cookies.set("salary_user", cookie)
    response = client.get("/api-docs")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    login = client.get(response.headers["location"])
    assert login.status_code == 200
    assert "text/html" in login.headers["content-type"]
    api = client.get("/api/departments/own/periods/2050/1")
    assert api.status_code == 401
    assert api.json() == {"detail": "Требуется API-ключ"}


def test_copyable_commands_match_current_routes(scoped_client):
    client, _, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    response = client.get("/api-docs")
    assert response.status_code == 200
    parsed = Examples(); parsed.feed(response.text)
    assert len(parsed.targets) == len(set(parsed.targets))
    assert len(parsed.targets) >= 13
    for target in parsed.targets:
        command = shlex.split(parsed.blocks[target].replace("\\\n", ""))
        assert command[0] == "curl"
        method = command[command.index("-X") + 1]
        url = next(word for word in command if word.startswith("http://testserver/"))
        path = urlsplit(url).path
        scope = {"type": "http", "method": method, "path": path, "root_path": ""}
        assert any(route.matches(scope)[0] == Match.FULL for route in app.routes), target
        if path.startswith("/api/departments/"):
            assert command[command.index("-H") + 1] == "X-API-Key: sk_salary_..."
    download = shlex.split(parsed.blocks["copy-download-pdf"].replace("\\\n", ""))
    assert "--fail" in download and "--output" in download


def test_documentation_explains_auth_and_destructive_actions(scoped_client):
    client, _, _, _, user, _ = scoped_client
    client.cookies.set("salary_user", make_session_token(user.id))
    text = client.get("/api-docs").text
    for phrase in ("Вход в браузере не заменяет API-ключ", "Требуется API-ключ",
                   "Первый запуск", "Полностью ручные расчётки сохраняются",
                   "Пересчёт удаляет ручные корректировки", "validated: true", "pwd", "PowerShell"):
        assert phrase in text
    assert '"detail": "Требуется авторизация"' not in text
    result = client.get("/api/departments/own/periods/2050/1")
    assert result.status_code == 401
    assert result.json() == {"detail": "Требуется API-ключ"}
