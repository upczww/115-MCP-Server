"""Credential-free MCP wire tests. No 115 requests or real downloads are made."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_115_server.config import Settings
from mcp_115_server.server import configure_app_logging, main
from mcp_115_server.version import __version__


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_initialize_discovery_calls_and_resource(self):
        # Never inherit a developer's real account into a protocol smoke test.
        env = {k: v for k, v in os.environ.items() if not k.startswith(('P115_', 'FASTMCP_'))}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        with tempfile.TemporaryDirectory() as directory:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'mcp_115_server', '--transport', 'stdio',
                cwd=directory, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async def send(message):
                proc.stdin.write((json.dumps(message) + '\n').encode())
                await proc.stdin.drain()

            async def response(request_id):
                async with asyncio.timeout(30):
                    while True:
                        line = await proc.stdout.readline()
                        self.assertTrue(line, 'Server exited before replying')
                        # Every stdout line must be JSON-RPC, not a banner/debug log.
                        message = json.loads(line)
                        self.assertEqual(message.get('jsonrpc'), '2.0')
                        if message.get('id') == request_id:
                            return message

            try:
                await send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                    'protocolVersion': '2025-11-25', 'capabilities': {},
                    'clientInfo': {'name': '115-protocol-test', 'version': '1.0'},
                }})
                result = (await response(1))['result']
                self.assertEqual(result['protocolVersion'], '2025-11-25')
                self.assertEqual(result['serverInfo']['version'], __version__)
                self.assertIn('tools', result['capabilities'])
                self.assertIn('resources', result['capabilities'])
                await send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                await send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
                tools = {item['name']: item for item in (await response(2))['result']['tools']}
                self.assertEqual(len(tools), 58)
                for tool in tools.values():
                    self.assertEqual(tool['inputSchema']['type'], 'object')
                    self.assertIsInstance(tool['annotations']['readOnlyHint'], bool)
                self.assertTrue(tools['offline_list_tasks']['annotations']['readOnlyHint'])
                self.assertFalse(tools['offline_add_urls']['annotations']['readOnlyHint'])
                self.assertFalse(tools['offline_add_urls']['annotations']['idempotentHint'])
                self.assertTrue(tools['remove_entry']['annotations']['destructiveHint'])
                await send({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
                    'name': 'auth_status', 'arguments': {'validate_remote': False},
                }})
                auth = (await response(3))['result']
                self.assertFalse(auth.get('isError', False))
                self.assertFalse(auth['structuredContent']['configured'])
                await send({'jsonrpc': '2.0', 'id': 4, 'method': 'resources/read', 'params': {'uri': 'info://server'}})
                info = (await response(4))['result']['contents']
                self.assertEqual(info[0]['mimeType'], 'application/json')
                json.loads(info[0]['text'])
                await send({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {
                    'name': 'offline_add_urls', 'arguments': {'urls': []},
                }})
                invalid = (await response(5))['result']
                self.assertTrue(invalid['isError'])
            finally:
                proc.stdin.close()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except TimeoutError:
                    proc.terminate()
                    await proc.wait()
            self.assertEqual(proc.returncode, 0)
            self.assertFalse((Path(directory) / 'logs').exists())


class StartupTests(unittest.TestCase):
    def test_logging_does_not_write_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
        self.assertFalse(settings.p115_debug_logging)
        with patch.object(Path, 'mkdir') as mkdir:
            configure_app_logging(settings)
        mkdir.assert_not_called()

    def test_help_does_not_configure_file_logging(self):
        with patch.object(sys, 'argv', ['115-MCP-Server', '--help']), patch(
            'mcp_115_server.server.configure_app_logging'
        ) as configure, patch('sys.stdout'):
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 0)
        configure.assert_not_called()

    def test_streamable_http_alias(self):
        with patch.object(sys, 'argv', ['115-MCP-Server', '--transport', 'streamable_http']), patch(
            'mcp_115_server.server.create_server'
        ) as create, patch('mcp_115_server.server.configure_app_logging'):
            main()
        self.assertEqual(create.return_value.run.call_args.kwargs['transport'], 'http')


if __name__ == '__main__':
    unittest.main()
