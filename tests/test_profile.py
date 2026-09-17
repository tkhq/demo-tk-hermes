import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import select
import shutil
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import profile as subject
from profile import Failure


class ProfileTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('bun'), 'Bun is required for MCP smoke test')
    def test_bundled_broker_exposes_exact_profile_allowlist(self):
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/profile.py'),
            'broker', '--bun', shutil.which('bun'), '--mode', 'mock'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            def request(payload):
                process.stdin.write(json.dumps(payload) + '\n')
                process.stdin.flush()
                self.assertTrue(select.select([process.stdout], [], [], 15)[0], 'MCP response timeout')
                return json.loads(process.stdout.readline())
            reply = request({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                           'clientInfo': {'name': 'profile-test', 'version': '1'}}})
            self.assertIn('result', reply)
            process.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
            process.stdin.flush()
            reply = request({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
            self.assertEqual({tool['name'] for tool in reply['result']['tools']}, set(subject.TOOLS))
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()

    def test_mock_strips_ambient_credentials(self):
        with patch.dict(os.environ, {'TURNKEY_API_PRIVATE_KEY': 'private',
                                     'OPENAI_API_KEY': 'model', 'SBM_HEADLESS': 'false'}):
            env = subject.broker_environment('mock')
        self.assertNotIn('TURNKEY_API_PRIVATE_KEY', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertEqual(env['SBM_HEADLESS'], 'false')

    def test_real_mode_requires_private_complete_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broker.json'
            path.write_text(json.dumps({k: 'synthetic' for k in subject.BROKER_KEYS}))
            path.chmod(0o644)
            with self.assertRaises(Failure):
                subject.broker_environment('turnkey', path)
            path.chmod(0o600)
            env = subject.broker_environment('turnkey', path)
            self.assertEqual(env['TURNKEY_API_BASE_URL'], 'https://api.turnkey.com')
            path.write_text('{}')
            with self.assertRaises(Failure):
                subject.broker_environment('turnkey', path)
        with self.assertRaises(Failure):
            subject.broker_environment('turnkey')

    def test_configure_profile_has_only_broker_tools_and_host_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / 'distribution.yaml').write_text('name: tk-hermes\n')
            args = argparse.Namespace(profile_home=tmp, bun='/usr/local/bin/bun',
                model='operator-selected-model', provider='openrouter', mode='mock',
                broker_credentials=None, tk_config=None)
            subject.configure(args)
            config = json.loads((home / 'config.yaml').read_text())
            self.assertEqual(config['toolsets'], ['mcp-secure_browser'])
            server = config['mcp_servers']['secure_browser']
            self.assertEqual(server['tools']['include'], subject.TOOLS)
            self.assertFalse(server['sampling']['enabled'])
            self.assertIn(str(home / 'scripts' / 'profile.py'), server['args'])
            with self.assertRaises(Failure):
                subject.configure(args)

    def test_tk_config_wires_secret_env_as_secrets_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / 'distribution.yaml').write_text('name: tk-hermes\n')
            tk_config = home.parent / (home.name + '-tk.json')
            tk_config.write_text(json.dumps({'tk': '/opt/tk/bin/tk', 'profile': 'agent',
                'name_prefix': 'agent/', 'property': 'consensus=unilateral'}))
            try:
                args = argparse.Namespace(profile_home=tmp, bun='/usr/local/bin/bun',
                    model='operator-selected-model', provider='openrouter', mode='mock',
                    broker_credentials=None, tk_config=str(tk_config))
                with patch.object(Path, 'home', return_value=Path('/home/op er')):
                    subject.configure(args)
            finally:
                tk_config.unlink()
            secrets = json.loads((home / 'config.yaml').read_text())['secrets']['command']
            self.assertTrue(secrets['enabled'])
            self.assertTrue(secrets['override_existing'])
            self.assertEqual(secrets['helper_timeout_seconds'], 30)
            self.assertEqual(secrets['command'],
                "HOME='/home/op er' /opt/tk/bin/tk --profile agent secret env "
                "--name-prefix agent/ --property consensus=unilateral")

    def test_tk_config_rejects_shell_metacharacters_and_missing_fields(self):
        good = {'tk': '/opt/tk/bin/tk', 'profile': 'agent', 'name_prefix': 'agent/',
                'property': 'consensus=unilateral'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tk.json'
            path.write_text(json.dumps(good))
            self.assertEqual(subject.load_tk_config(path), good)
            for key, value in [('tk', 'tk'), ('profile', 'agent; rm -rf /'),
                               ('name_prefix', 'agent'), ('name_prefix', '$(id)/'),
                               ('property', 'consensus'), ('property', "a='b'"),
                               ('profile', None)]:
                bad = dict(good)
                bad[key] = value
                path.write_text(json.dumps(bad))
                with self.assertRaises(Failure, msg=(key, value)):
                    subject.load_tk_config(path)


if __name__ == '__main__':
    unittest.main()
