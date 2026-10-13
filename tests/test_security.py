import asyncio
import unittest
from unittest.mock import Mock, patch

import httpx

from vigilo_connector import auth, server
from vigilo_connector.client import VigiloClient
from vigilo_connector.config import API_BASE, WEB_API_BASE


class RequestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock(spec=auth.TokenStore)
        self.store.access_token.return_value = "offline-test-token"
        self.client = VigiloClient(self.store)
        self.client.close()
        self.requests = []
        self.responses = []

        def respond(request):
            self.requests.append(request)
            if self.responses:
                return self.responses.pop(0)
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(respond)
        self.client._http = httpx.Client(transport=transport, follow_redirects=True)
        self.client._web = httpx.Client(transport=transport, follow_redirects=True)
        self.addCleanup(self.client.close)

    def test_untrusted_routes_rejected_before_token_access_or_request(self):
        paths = [
            "https://attacker.invalid/api/children",
            "http://attacker.invalid/api/children",
            "//attacker.invalid/api/children",
            "https://api-gw-parent-app.prod.vigilo-oas.no@attacker.invalid/api/children",
            "https://web-parent.prod.vigilo-oas.no.attacker.invalid/api/children/my",
            "/api/children?redirect=https://attacker.invalid",
            "/api/children#fragment",
            "/api/children\n",
            " /api/children",
            "/api/../children",
            "/api/messages/threads/../../children",
            "/api/messages/threads/%2e%2e",
            "/api/messages/threads/a%2fb",
            "/api/posts/a/attachments/../../current-user",
            "/api/students/a/../current-user/lessons",
            "/api/scheduling-events/a?x=1/student",
            "/api/messages/threads/a\\b",
            "/api/unknown",
            "/connect/token",
            "api/children",
            "",
        ]
        for method in (self.client.get, self.client.web_get):
            for path in paths:
                with self.subTest(method=method.__name__, path=path):
                    with self.assertRaises(ValueError):
                        method(path)
        self.store.access_token.assert_not_called()
        self.assertEqual(self.requests, [])

    def test_known_app_routes_keep_fixed_origin_and_parameters(self):
        for path in (
            "/api/children",
            "/api/message-threads",
            "/api/messages/threads/test-thread_1",
        ):
            with self.subTest(path=path):
                response = self.client.get(path, {"pageSize": 50})
                self.assertEqual(response.status_code, 200)
                request = self.requests[-1]
                self.assertEqual(str(request.url.copy_with(query=None)), API_BASE + path)
                self.assertEqual(request.url.params["pageSize"], "50")
                self.assertEqual(request.headers["authorization"], "Bearer offline-test-token")

    def test_known_web_routes_keep_fixed_origin(self):
        for path in (
            "/api/children/my",
            "/api/current-user",
            "/api/news-feed",
            "/api/message-threads",
            "/api/absences",
            "/api/consent-forms",
            "/api/students/test-child/lessons",
            "/api/scheduling-events/test-child/student",
            "/api/school-years",
            "/api/posts/test-post",
            "/api/posts/test-post/attachments/test-attachment",
        ):
            with self.subTest(path=path):
                self.client.web_get(path)
                request = self.requests[-1]
                self.assertEqual(str(request.url), WEB_API_BASE + path)
                self.assertEqual(request.headers["authorization"], "Bearer offline-test-token")
                self.assertNotIn("appVersion", request.headers)

    def test_api_routes_are_not_interchangeable(self):
        with self.assertRaises(ValueError):
            self.client.get("/api/children/my")
        with self.assertRaises(ValueError):
            self.client.web_get("/api/messages/threads/test-thread")
        self.store.access_token.assert_not_called()

    def test_query_values_cannot_change_authenticated_origin(self):
        self.client.web_get("/api/news-feed", {"childIds": "https://attacker.invalid"})
        self.assertEqual(self.requests[0].url.host, httpx.URL(WEB_API_BASE).host)
        self.assertEqual(len(self.requests), 1)

    def test_redirects_never_receive_credentials(self):
        for method, path in (
            (self.client.get, "/api/children"),
            (self.client.web_get, "/api/children/my"),
        ):
            for status in (301, 302, 303, 307, 308):
                with self.subTest(method=method.__name__, status=status):
                    self.requests.clear()
                    self.responses = [
                        httpx.Response(status, headers={"Location": "https://attacker.invalid"})
                    ]
                    response = method(path)
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(len(self.requests), 1)
                    self.assertNotEqual(self.requests[0].url.host, "attacker.invalid")

    def test_401_refresh_stays_on_fixed_origin(self):
        for method, path, base in (
            (self.client.get, "/api/children", API_BASE),
            (self.client.web_get, "/api/children/my", WEB_API_BASE),
        ):
            with self.subTest(method=method.__name__):
                self.store.reset_mock()
                refresh_requests = []

                def token(force_refresh=False):
                    refresh_requests.append(force_refresh)
                    return "offline-test-token"

                self.store.access_token.side_effect = token
                self.requests.clear()
                self.responses = [httpx.Response(401), httpx.Response(200, json={})]
                self.assertEqual(method(path).status_code, 200)
                self.assertEqual(len(self.requests), 2)
                self.assertTrue(all(str(r.url) == base + path for r in self.requests))
                self.assertEqual(refresh_requests, [False, True])


class ToolSurfaceTests(unittest.TestCase):
    def test_only_named_operations_are_exposed(self):
        tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual(
            {tool.name for tool in tools},
            {
                "list_children",
                "list_message_threads",
                "get_message_thread",
                "read_message_attachments",
                "read_post_attachments",
                "web_list_children",
                "news_feed",
                "absences",
                "consent_forms",
                "timetable",
                "scheduling_events",
            },
        )


class AuthErrorPrivacyTests(unittest.TestCase):
    @patch("vigilo_connector.auth._basic_auth", return_value="offline-test-client")
    @patch("vigilo_connector.auth.httpx.post")
    def test_rejected_token_response_is_not_reflected(self, post, basic_auth):
        for status in (400, 401):
            post.return_value = httpx.Response(status, text="PRIVATE_RESPONSE_SENTINEL")
            with self.assertRaises(auth.AuthError) as raised:
                auth.exchange_code("offline-test-code")
            self.assertNotIn("PRIVATE_RESPONSE_SENTINEL", str(raised.exception))
            self.assertIn(str(status), str(raised.exception))

    @patch("vigilo_connector.auth.authorize_url", return_value="https://auth.invalid")
    @patch("vigilo_connector.auth.httpx.get")
    def test_failed_callback_is_not_reflected(self, get, authorize_url):
        get.return_value = httpx.Response(
            302, headers={"Location": "app://callback?error=PRIVATE_CALLBACK_SENTINEL"}
        )
        with self.assertRaises(auth.AuthError) as raised:
            auth.code_from_cookies("offline-test-cookie")
        self.assertNotIn("PRIVATE_CALLBACK_SENTINEL", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
