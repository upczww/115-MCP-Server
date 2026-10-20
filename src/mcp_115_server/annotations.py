"""Portable MCP tool hints; clients must still enforce their own authorization."""

READ_ONLY_TOOLS = frozenset({
    "auth_status", "get_qrcode_login_status", "list_directory", "get_metadata",
    "search_entries", "resolve_directory", "get_storage_info", "get_account_info",
    "get_index_info", "path_exists", "count_directory", "get_ancestors",
    "glob_entries", "walk_directory", "get_stat", "offline_get_torrent_info",
    "offline_list_tasks", "offline_list_tasks_advanced", "offline_find_tasks",
    "offline_get_quota_info", "offline_get_sign_info", "offline_get_quota_package_array",
    "offline_get_quota_package_info", "offline_get_download_paths", "offline_get_task_count",
    "list_recycle_bin", "get_recycle_bin_entry", "list_labels", "list_shares",
    "get_share_info", "get_share_receive_code", "get_share_download_url",
    "list_share_access_users", "get_share_download_quota", "get_download_url",
})

NON_DESTRUCTIVE_WRITES = frozenset({
    "start_qrcode_login", "finish_qrcode_login", "create_directory",
    "offline_add_urls", "offline_add_torrent", "offline_restart_task",
    "restore_recycle_bin_entries", "receive_share_entries",
})


def tool_annotations(name: str) -> dict[str, bool]:
    read_only = name in READ_ONLY_TOOLS
    return {
        "readOnlyHint": read_only,
        "destructiveHint": not read_only and name not in NON_DESTRUCTIVE_WRITES,
        "idempotentHint": read_only,
        "openWorldHint": True,
    }
