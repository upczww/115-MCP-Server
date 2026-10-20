"""Real filesystem contracts; mock only network boundaries, never real cookies."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from weakref import WeakValueDictionary

from p115client import P115Client
from p115client.fs import P115FileSystem

from mcp_115_server.compat import _AttributeCache, prepare_filesystem
from mcp_115_server.config import Settings
from mcp_115_server.service import P115Service


def attr(name="电视剧"):
    return {"id": 7, "parent_id": 0, "name": name, "is_dir": True, "size": 0}


class FilesystemCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(P115Client)
        self.fs = prepare_filesystem(P115FileSystem(self.client))

    def test_cold_id_lookup_accepts_plain_dict(self):
        value = attr()
        with patch("p115client.fs.fs.get_attr", return_value=value) as backend:
            self.assertIs(self.fs.get_attr(7), value)
            self.assertIs(self.fs.get_attr(7), value)
        self.assertEqual(backend.call_count, 1)

    def test_refresh_keeps_identity_and_fetches_new_value(self):
        with patch("p115client.fs.fs.get_attr", side_effect=[attr(), attr("新名称")]) as backend:
            first = self.fs.get_attr(7)
            refreshed = self.fs.get_attr(7, refresh=True)
        self.assertIs(first, refreshed)
        self.assertEqual(first["name"], "新名称")
        self.assertEqual(backend.call_count, 2)

    def test_async_attribute_lookup(self):
        async def result(*args, **kwargs):
            return attr()
        with patch("p115client.fs.fs.get_attr", side_effect=result):
            self.assertEqual(asyncio.run(self.fs.get_attr(7, refresh=True, async_=True))["id"], 7)

    def test_name_index_accepts_same_plain_dict_without_copy(self):
        value = attr()
        self.fs.id_to_attr[7] = value
        self.fs._pid_name_to_attr[(0, "电视剧")] = value
        self.assertIs(self.fs.id_to_attr[7], self.fs._pid_name_to_attr[(0, "电视剧")])

    def test_only_this_filesystem_is_changed(self):
        untouched = P115FileSystem(self.client)
        self.assertIsInstance(untouched.id_to_attr, WeakValueDictionary)
        self.assertIsInstance(untouched._pid_name_to_attr, WeakValueDictionary)
        existing = self.fs.id_to_attr
        self.assertIs(prepare_filesystem(self.fs).id_to_attr, existing)

    def test_existing_nonweak_cache_is_preserved(self):
        values = {7: attr()}
        fs = SimpleNamespace(id_to_attr=values)
        self.assertIs(prepare_filesystem(fs).id_to_attr, values)

    def test_cache_is_bounded_for_assignment_and_update(self):
        cache = _AttributeCache(maxsize=2)
        cache.update({1: {}, 2: {}, 3: {}})
        self.assertEqual(list(cache), [2, 3])
        cache[2] = {"updated": True}
        cache[4] = {}
        self.assertEqual(list(cache), [2, 4])
        self.assertEqual(cache.pop(2), {"updated": True})
        cache.clear()
        self.assertFalse(cache)

    def test_service_prepares_lazy_filesystem(self):
        service = P115Service(Settings(P115_COOKIES="fake", P115_DEBUG_LOGGING=False))
        service._get_client_for_platform = lambda *args, **kwargs: self.client
        with patch("p115client.fs.fs.get_attr", return_value=attr()):
            fs = service._get_fs_for_platform(None)
            self.assertEqual(fs.get_attr(7, refresh=True)["name"], "电视剧")
        self.assertIs(service._get_fs_for_platform(None), fs)

    def test_service_prepares_active_platform_filesystem(self):
        service = P115Service(Settings(P115_COOKIES="fake", P115_DEBUG_LOGGING=False))
        service._effective_platform = lambda *args: "web"
        service._remember_active_platform(None, client=self.client)
        with patch("p115client.fs.fs.get_attr", return_value=attr()):
            self.assertEqual(service._fs_instance.get_attr(7, refresh=True)["name"], "电视剧")
        service._reset_client_state()
        self.assertFalse(service._fs_cache)
        self.assertIsNone(service._fs_instance)

    def test_service_directory_list_with_real_attribute_cache(self):
        service = P115Service(Settings(P115_COOKIES="fake", P115_DEBUG_LOGGING=False))
        service._get_client_for_platform = lambda *args, **kwargs: self.client
        service._list_directory_entries = lambda directory_id: [{"id": 8, "name": "测试剧集", "is_dir": True}]
        with patch("p115client.fs.fs.get_attr", return_value=attr()):
            result = service.list_directory(remote_id="7", refresh=True)
        self.assertEqual(result["directory"]["name"], "电视剧")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entries"][0]["name"], "测试剧集")


if __name__ == "__main__":
    unittest.main()
