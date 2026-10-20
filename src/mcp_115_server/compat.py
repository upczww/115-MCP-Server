"""Small, capability-based bridge between p115client's old and current APIs.

Only cookie P115Client methods are selected. Do not bind P115OpenClient methods:
those use a different authorization model. Selection happens before a call and
never retries a dispatched mutation on a second endpoint.
"""
from __future__ import annotations

import inspect
from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable

from fastmcp.exceptions import ToolError


OFFLINE_METHODS = {
    "offline_add_urls": "clouddownload_task_add_urls",
    "offline_add_urls_open": "clouddownload_task_add_urls",
    "offline_list": "clouddownload_task_list",
    "offline_list_open": "clouddownload_task_list",
    "offline_remove": "clouddownload_task_del",
    "offline_remove_open": "clouddownload_task_del",
    "offline_clear_open": "clouddownload_task_clear",
    "offline_quota_info_open": "clouddownload_quota_info",
    "offline_sign": "clouddownload_sign",
    "offline_quota_package_array": "clouddownload_quota_package_array",
    "offline_quota_package_info": "clouddownload_quota_package_info",
    "offline_download_path": "clouddownload_downpath",
    "offline_download_path_set": "clouddownload_downpath_set",
    "offline_restart": "clouddownload_task_restart",
    # task_count takes NO flag; get_task_cnt is the flag-taking old contract.
    "offline_task_count": "clouddownload_task_cnt",
    "offline_torrent_info_open": "clouddownload_torrent",
    "offline_add_torrent_open": "clouddownload_task_add_bt",
}

OFFLINE_MUTATIONS = frozenset({
    "offline_add_urls", "offline_add_urls_open", "offline_add_torrent",
    "offline_add_torrent_open", "offline_remove_task", "offline_remove_tasks",
    "offline_remove", "offline_remove_open", "offline_clear_tasks",
    "offline_clear_open", "offline_download_path_set", "offline_restart",
})


def client_kwargs(client_type: type, *, app: str | None, console_qrcode: bool,
                  check_for_relogin: bool) -> dict[str, Any]:
    """Pass the removed relogin argument only when explicitly supported."""
    params = inspect.signature(client_type.__init__).parameters
    kwargs: dict[str, Any] = {"app": app or "", "console_qrcode": console_qrcode}
    if "check_for_relogin" in params:
        kwargs["check_for_relogin"] = check_for_relogin
    return kwargs


def has_modern_offline(client: Any, old_name: str) -> bool:
    return callable(getattr(client, OFFLINE_METHODS.get(old_name, ""), None))


def offline_method(client: Any, name: str) -> Callable:
    """Return one callable, translating its old payload without network I/O."""
    modern_name = OFFLINE_METHODS.get(name)
    modern = getattr(client, modern_name, None) if modern_name else None
    if not callable(modern):
        legacy = getattr(client, name, None)
        if not callable(legacy):
            raise ToolError(f"Installed p115client supports neither {name} nor {modern_name}; install the supported version.")
        return legacy

    @wraps(modern)
    def call(*args, **kwargs):
        args = list(args)
        if args and isinstance(args[0], Mapping):
            args[0] = dict(args[0])  # current library mutates request dictionaries
        if name == "offline_add_urls_open" and args:
            payload = args[0]
            if isinstance(payload, dict) and "urls" in payload:
                urls = payload.pop("urls")
                urls = urls.splitlines() if isinstance(urls, str) else urls
                payload.update({f"url[{i}]": url for i, url in enumerate(urls)})
        elif name == "offline_remove_open" and args:
            payload = args[0]
            if isinstance(payload, dict):
                payload["hash[0]"] = payload.pop("info_hash")
                payload["flag"] = payload.pop("del_source_file", 0)
        elif name == "offline_torrent_info_open" and args:
            payload = args[0]
            if isinstance(payload, dict):
                args[0] = {"sha1": payload["torrent_sha1"]}
        elif name == "offline_add_torrent_open" and args:
            payload = args[0]
            if isinstance(payload, dict):
                payload.pop("torrent_sha1", None)
                payload.pop("pick_code", None)
                if "save_path" in payload:
                    payload["savepath"] = payload.pop("save_path")
                if not payload.get("info_hash"):
                    raise ToolError("A torrent info_hash is required by the cookie cloud-download API.")
        return modern(*args, **kwargs)

    return call


def task_page(response: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize root/web and nested/app list envelopes without losing metadata."""
    nested = response.get("data")
    data = dict(response)
    if isinstance(nested, Mapping):
        data.update(nested)
    tasks = data.get("tasks")
    if tasks is None and isinstance(nested, list):
        tasks = nested
    if tasks is None:
        # Do not mistake a malformed response for proof there are no tasks.
        if data.get("count") in (0, "0"):
            tasks = []
        else:
            raise ToolError("Cloud-download response has no task list; task state is unknown.")
    if not isinstance(tasks, list) or any(not isinstance(item, Mapping) for item in tasks):
        raise ToolError("Cloud-download response contains an invalid task list.")
    data["tasks"] = [dict(item) for item in tasks]
    if data.get("page_count") is None and data.get("page_size") and data.get("count") is not None:
        try:
            size, count = int(data["page_size"]), int(data["count"])
            if size > 0:
                data["page_count"] = max(1, (count + size - 1) // size)
        except (ValueError, TypeError):
            pass
    return data
