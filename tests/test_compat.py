"""Contract tests use real p115client methods, with all network boundaries mocked."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from fastmcp.exceptions import ToolError
from p115client import P115Client

from mcp_115_server.compat import OFFLINE_METHODS, client_kwargs, offline_method, task_page
from mcp_115_server.config import Settings
from mcp_115_server.service import P115Service


class ContractClient(P115Client):
    """Skip initialization and record calls below the actual public API bodies."""
    def __init__(self):
        self.calls = []
        self.response = {"state": True, "data": {"info_hash": "torrent-hash"}}
        self.fail = None

    def clouddownload_request(self, payload=None, action="", **kwargs):
        self.calls.append((action, dict(payload or {}), kwargs))
        if self.fail:
            raise self.fail
        return self.response

    def request(self, **kwargs):
        self.calls.append(("request", kwargs, {}))
        if self.fail:
            raise self.fail
        return self.response


def make_service(client):
    service = P115Service(Settings(P115_COOKIES="test-not-a-real-cookie", P115_DEBUG_LOGGING=False))
    service._get_client_for_platform = lambda platform, **kwargs: client
    service._remember_active_platform = lambda platform, client=None: None
    return service


class ModernContracts(unittest.TestCase):
    def setUp(self):
        self.client = ContractClient()
        self.service = make_service(self.client)

    def test_every_modern_method_exists_on_cookie_client(self):
        for method in OFFLINE_METHODS.values():
            with self.subTest(method=method):
                self.assertTrue(callable(getattr(P115Client, method, None)))

    def test_constructor_does_not_pass_removed_keyword(self):
        kwargs = client_kwargs(P115Client, app=None, console_qrcode=False, check_for_relogin=True)
        self.assertNotIn("check_for_relogin", kwargs)
        self.assertEqual(kwargs["app"], "")

    def test_legacy_constructor_keeps_supported_keyword(self):
        class Legacy:
            def __init__(self, cookies=None, app=None, check_for_relogin=False, console_qrcode=False):
                pass
        self.assertTrue(client_kwargs(Legacy, app="web", console_qrcode=False, check_for_relogin=True)["check_for_relogin"])

    def test_service_constructor_guard(self):
        class Modern:
            def __init__(self, cookies=None, app="", console_qrcode=True):
                self.app = app
        with patch("mcp_115_server.service.P115Client", Modern):
            svc = P115Service(Settings(P115_COOKIES="fake", P115_DEBUG_LOGGING=False))
            self.assertEqual(svc._get_client_for_platform(None).app, "")

    def test_add_urls_uses_indexed_payload_and_preserves_destination(self):
        self.service.offline_add_urls(["https://example.test/a", "magnet:?xt=urn:btih:test"], remote_dir_id="12345678901234567")
        action, payload, kwargs = self.client.calls[0]
        self.assertEqual(action, "add_task_urls")
        self.assertEqual(payload["url[1]"], "magnet:?xt=urn:btih:test")
        self.assertEqual(payload["wp_path_id"], 12345678901234567)
        self.assertEqual(kwargs["type"], "web")
        self.assertEqual(len(self.client.calls), 1)

    def test_legacy_open_payload_is_translated_without_mutating_input(self):
        payload = {"urls": "https://example.test/a\nhttps://example.test/b", "wp_path_id": 7}
        offline_method(self.client, "offline_add_urls_open")(payload, type="web")
        self.assertIn("urls", payload)
        self.assertEqual(self.client.calls[-1][1]["url[1]"], "https://example.test/b")
        self.assertNotIn("urls", self.client.calls[-1][1])

    def test_task_list_nested_response(self):
        self.client.response = {"state": True, "data": {"count": 1, "page_count": 1, "tasks": [{"info_hash": "a"}]}}
        result = self.service.offline_list_tasks()
        self.assertEqual(result["tasks"], [{"info_hash": "a"}])
        self.assertEqual(self.client.calls[-1][0], "task_lists")

    def test_advanced_task_list_preserves_filters_and_nested_count(self):
        self.client.response = {"state": True, "data": {"count": 1, "page_count": 2, "tasks": [{"info_hash": "a"}]}}
        result = self.service.offline_list_tasks_advanced(page=2, page_size=20, status="completed")
        self.assertEqual(self.client.calls[-1][1], {"page": 2, "page_size": 20, "stat": 11})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["page_count"], 2)

    def test_find_tasks_uses_modern_task_list(self):
        self.client.response = {"state": True, "count": 1, "page_count": 1, "tasks": [{"info_hash": "a", "name": "example"}]}
        self.assertEqual(self.service.offline_find_tasks(query="example")["count"], 1)

    def test_count_flag_uses_cnt_not_no_argument_count(self):
        self.service.offline_get_task_count(flag=3)
        self.assertEqual(self.client.calls[-1][0], "get_task_cnt")
        self.assertEqual(self.client.calls[-1][1]["flag"], 3)

    def test_quota_uses_cookie_api_not_open_superclass(self):
        self.service.offline_get_quota_info()
        self.assertEqual(self.client.calls[-1][0], "get_quota_info")
        self.assertEqual(self.client.calls[-1][2]["base_url"], "https://clouddownload.115.com")
        self.assertEqual(self.client.calls[-1][2]["type"], "web")

    def test_auxiliary_read_methods_use_modern_names(self):
        for method in ("offline_get_sign_info", "offline_get_quota_package_array", "offline_get_quota_package_info", "offline_get_download_paths"):
            with self.subTest(method=method):
                self.client.calls.clear()
                getattr(self.service, method)()
                self.assertEqual(len(self.client.calls), 1)

    def test_set_default_directory(self):
        self.service._fs_call = lambda *a, **k: {"id": "7", "is_dir": True}
        self.service.offline_set_download_path(remote_dir_id="7")
        self.assertEqual(self.client.calls[-1][0], "request")
        self.assertIn("7", str(self.client.calls[-1][1]))

    def test_torrent_info_uses_sha1_not_pickcode(self):
        self.service.offline_get_torrent_info("file-sha1", "pick")
        self.assertEqual(self.client.calls[-1][0:2], ("torrent", {"sha1": "file-sha1"}))

    def test_add_torrent_looks_up_missing_info_hash_and_translates_savepath(self):
        self.service.offline_add_torrent(torrent_sha1="file-sha1", pick_code="pick", wanted_indexes=[0, 2], save_path="folder", remote_dir_id="7")
        self.assertEqual([c[0] for c in self.client.calls], ["torrent", "add_task_bt"])
        payload = self.client.calls[-1][1]
        self.assertEqual(payload, {"info_hash": "torrent-hash", "wanted": "0,2", "savepath": "folder", "wp_path_id": 7})

    def test_add_torrent_with_hash_does_not_query_metadata(self):
        self.service.offline_add_torrent(torrent_sha1="file-sha1", pick_code="pick", info_hash="explicit")
        self.assertEqual([c[0] for c in self.client.calls], ["add_task_bt"])

    def test_missing_torrent_hash_never_submits(self):
        self.client.response = {"state": True, "data": {"files": []}}
        with self.assertRaisesRegex(ToolError, "no info_hash"):
            self.service.offline_add_torrent(torrent_sha1="file-sha1", pick_code="pick")
        self.assertEqual([c[0] for c in self.client.calls], ["torrent"])

    def test_remove_translates_hashes_and_flag(self):
        self.client.response = {"state": True, "count": 0, "page_count": 1, "tasks": []}
        result = self.service.offline_remove_task("a", delete_source_file=True)
        self.assertTrue(result["removed"])
        self.assertEqual(self.client.calls[0][0:2], ("task_del", {"hash[0]": "a", "flag": 1}))

    def test_remove_many(self):
        self.client.response = {"state": True, "count": 0, "page_count": 1, "tasks": []}
        self.assertEqual(self.service.offline_remove_tasks(["a", "b"])["removed"], ["a", "b"])

    def test_clear_flags(self):
        for scope, flag in (("completed", 0), ("all", 1), ("failed", 2), ("in_progress", 3), ("completed_and_delete_source", 4), ("all_and_delete_source", 5)):
            with self.subTest(scope=scope):
                self.service.offline_clear_tasks(scope)
                self.assertEqual(self.client.calls[-1][0:2], ("task_clear", {"flag": flag}))

    def test_restart(self):
        self.service.offline_restart_task("a")
        self.assertEqual(self.client.calls[-1][0:2], ("restart", {"info_hash": "a"}))

    def test_ambiguous_add_never_retries_any_endpoint_or_platform(self):
        for error in (TimeoutError("authorization response timed out"), RuntimeError("authorization"), TypeError("bad response")):
            with self.subTest(error=type(error).__name__):
                self.client.calls.clear()
                self.client.fail = error
                self.service._platform_candidates = lambda preferred=None: ["web", None]
                with self.assertRaisesRegex(ToolError, "No automatic retry"):
                    self.service.offline_add_urls(["https://example.test/a"])
                self.assertEqual(len(self.client.calls), 1)

    def test_other_mutations_never_retry_after_uncertain_error(self):
        self.client.fail = TimeoutError("authorization")
        self.service._platform_candidates = lambda preferred=None: ["web", None]
        operations = [lambda: self.service.offline_clear_tasks(), lambda: self.service.offline_restart_task("a"), lambda: self.service.offline_remove_task("a"), lambda: self.service.offline_add_torrent(torrent_sha1="sha", pick_code="pick", info_hash="hash")]
        for operation in operations:
            with self.subTest(operation=operation):
                self.client.calls.clear()
                with self.assertRaisesRegex(ToolError, "No automatic retry"):
                    operation()
                self.assertEqual(len(self.client.calls), 1)

    def test_legacy_client_still_supported_without_modern_methods(self):
        legacy = Mock(spec=["offline_list"])
        legacy.offline_list.return_value = {"state": True, "tasks": [], "count": 0}
        self.assertEqual(offline_method(legacy, "offline_list")({"page": 1})["count"], 0)

    def test_invalid_response_is_not_empty_task_state(self):
        for response in ({"state": True}, {"state": True, "tasks": "wrong"}, {"state": True, "tasks": [1]}):
            with self.subTest(response=response):
                with self.assertRaises(ToolError):
                    task_page(response)

    def test_root_counts_not_lost_with_nested_data(self):
        page = task_page({"state": True, "count": 31, "page_size": 30, "data": {"tasks": []}})
        self.assertEqual(page["page_count"], 2)


if __name__ == "__main__":
    unittest.main()
