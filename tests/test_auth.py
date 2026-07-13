import json
from http.server import HTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import (  # noqa: E402
    ControlPlane,
    DecisionPolicy,
    InMemoryAuditSink,
    InMemoryAuthStore,
    InMemoryControlPlaneStore,
    LocalAuthService,
    RuleBasedModelWrapper,
    RuntimeEngine,
)
from tenta_runtime.api import make_handler  # noqa: E402
from tenta_runtime.console_api import ConsoleRoutes  # noqa: E402


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.static_dir = tempfile.TemporaryDirectory()
        static_path = Path(self.static_dir.name)
        (static_path / "index.html").write_text("<!doctype html><title>Tenta</title>", encoding="utf-8")
        self.engine = RuntimeEngine(
            model=RuleBasedModelWrapper(),
            policy=DecisionPolicy(),
            audit_sink=InMemoryAuditSink(),
        )
        self.control_plane = ControlPlane(store=InMemoryControlPlaneStore())
        self.console = ConsoleRoutes(self.engine, self.control_plane)
        self.auth = LocalAuthService(InMemoryAuthStore())
        self.server = HTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.engine, static_dir=static_path, console=self.console, auth=self.auth),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.static_dir.cleanup()

    def test_bootstrap_creates_admin_session_and_protects_console(self):
        status = self._get_json("/v1/auth/status")
        self.assertTrue(status["needs_bootstrap"])

        bootstrap, cookie = self._post_json_with_cookie(
            "/v1/auth/bootstrap",
            {
                "email": "admin@tenta.local",
                "display_name": "Admin",
                "password": "correct horse battery staple",
            },
        )
        self.assertEqual(bootstrap["user"]["role"], "admin")
        self.assertIn("tenta_session=", cookie)

        with self.assertRaises(HTTPError) as error:
            self._get_json("/v1/overview")
        self.assertEqual(error.exception.code, 401)

        overview = self._get_json("/v1/overview", cookie=cookie)
        self.assertEqual(overview["health"]["status"], "healthy")
        me = self._get_json("/v1/auth/me", cookie=cookie)
        self.assertEqual(me["user"]["email"], "admin@tenta.local")

    def test_api_key_authenticates_protected_console_requests(self):
        _, cookie = self._post_json_with_cookie(
            "/v1/auth/bootstrap",
            {
                "email": "admin@tenta.local",
                "display_name": "Admin",
                "password": "correct horse battery staple",
            },
        )
        created = self._post_json(
            "/v1/auth/api-keys",
            {"label": "cli", "role": "model-risk"},
            cookie=cookie,
        )
        token = created["token"]
        self.assertTrue(token.startswith("tenta_key_"))

        models = self._get_json("/v1/models", api_key=token)
        self.assertEqual(models["champion"], "fraud-xgb-v12")

    def _get_json(self, path, *, cookie=None, api_key=None):
        request = Request(self.base_url + path, method="GET", headers=self._headers(cookie=cookie, api_key=api_key))
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path, payload, *, cookie=None, api_key=None):
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=self._headers(cookie=cookie, api_key=api_key),
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json_with_cookie(self, path, payload):
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8")), response.headers.get("Set-Cookie")

    def _headers(self, *, cookie=None, api_key=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers


if __name__ == "__main__":
    unittest.main()
