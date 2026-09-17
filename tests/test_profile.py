import argparse
import filecmp
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import profile as subject
from profile import Failure


def configure_args(tmp, **overrides):
    values = dict(profile_home=tmp, bun='/usr/local/bin/bun', model=None, provider=None,
                  mode='mock', broker_credentials=None, organization_id=None, tk=None,
                  tk_profile='hermes')
    values.update(overrides)
    return argparse.Namespace(**values)


def private_file(directory, name, payload):
    path = Path(directory) / name
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    return path


class BrokerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('bun'), 'Bun is required for MCP smoke test')
    def test_bundled_broker_exposes_the_profile_allowlist(self):
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
            served = {tool['name'] for tool in reply['result']['tools']}
            # The allowlist is a subset of what the broker serves; the one tool it
            # leaves out is the upstream not_implemented stub.
            self.assertTrue(set(subject.TOOLS) <= served)
            self.assertEqual(served - set(subject.TOOLS), {'list_network_requests'})
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()

    def test_mock_strips_ambient_credentials(self):
        with patch.dict(os.environ, {'TURNKEY_API_PRIVATE_KEY': 'private',
                                     'OPENAI_API_KEY': 'model', 'SBM_HEADLESS': 'false',
                                     'SBM_DASHBOARD_URL': 'https://dash.example.test'}):
            env = subject.broker_environment('mock')
        self.assertNotIn('TURNKEY_API_PRIVATE_KEY', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertEqual(env['SBM_HEADLESS'], 'false')
        self.assertEqual(env['SBM_DASHBOARD_URL'], 'https://dash.example.test')

    def test_real_mode_requires_private_complete_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = private_file(tmp, 'broker.json', {k: 'synthetic' for k in subject.BROKER_KEYS})
            path.chmod(0o644)
            with self.assertRaises(Failure):
                subject.broker_environment('turnkey', path)
            path.chmod(0o600)
            env = subject.broker_environment('turnkey', path)
            self.assertEqual(env['TURNKEY_API_BASE_URL'], 'https://api.turnkey.com')
            self.assertEqual(env['TURNKEY_ORGANIZATION_ID'], 'synthetic')
            path.write_text('{}')
            with self.assertRaises(Failure):
                subject.broker_environment('turnkey', path)
        with self.assertRaises(Failure):
            subject.broker_environment('turnkey')

    def test_dashboard_credential_file_needs_an_organization(self):
        dashboard = {'publicKey': '02ab', 'privateKey': 'cd', 'createdAt': 'ignored'}
        with tempfile.TemporaryDirectory() as tmp:
            path = private_file(tmp, 'turnkey-api-credentials-1.json', dashboard)
            with self.assertRaises(Failure):
                subject.broker_environment('turnkey', path)
            env = subject.broker_environment('turnkey', path, 'org-1')
            self.assertEqual(env['TURNKEY_API_PUBLIC_KEY'], '02ab')
            self.assertEqual(env['TURNKEY_API_PRIVATE_KEY'], 'cd')
            self.assertEqual(env['TURNKEY_ORGANIZATION_ID'], 'org-1')
            # Both file shapes launch the broker with the same variables.
            three_key = private_file(tmp, 'broker.json', {
                'TURNKEY_API_PUBLIC_KEY': '02ab', 'TURNKEY_API_PRIVATE_KEY': 'cd',
                'TURNKEY_ORGANIZATION_ID': 'org-1'})
            self.assertEqual(subject.broker_environment('turnkey', three_key),
                             subject.broker_environment('turnkey', path, 'org-1'))
            with self.assertRaises(Failure):
                subject.broker_environment('turnkey', three_key, 'other-org')


class ConfigureTests(unittest.TestCase):
    def write_home(self, tmp):
        home = Path(tmp).resolve()
        (home / 'distribution.yaml').write_text('name: tk-hermes\n')
        return home

    def test_configure_leaves_only_broker_tools_and_host_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self.write_home(tmp)
            args = configure_args(tmp, model='operator-selected-model', provider='openrouter')
            subject.configure(args)
            config = json.loads((home / 'config.yaml').read_text())
            self.assertNotIn('toolsets', config)  # deprecated key Hermes ignores
            for platform in ('cli', 'photon', 'telegram'):
                self.assertEqual(config['platform_toolsets'][platform], [subject.SERVER])
            for toolset in ('terminal', 'file', 'browser', 'code_execution'):
                self.assertIn(toolset, config['agent']['disabled_toolsets'])
            server = config['mcp_servers'][subject.SERVER]
            self.assertEqual(server['tools']['include'], subject.TOOLS)
            self.assertNotIn('list_network_requests', server['tools']['include'])
            self.assertFalse(server['sampling']['enabled'])
            self.assertIn(str(home / 'scripts' / 'profile.py'), server['args'])
            self.assertEqual(config['model'], {'default': 'operator-selected-model',
                                               'provider': 'openrouter'})
            self.assertNotIn('secrets', config)
            with self.assertRaises(Failure):
                subject.configure(args)

    def test_model_is_optional_but_comes_with_its_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self.write_home(tmp)
            with self.assertRaises(Failure):
                subject.configure(configure_args(tmp, model='only-model'))
            subject.configure(configure_args(tmp))
            config = json.loads((home / 'config.yaml').read_text())
            self.assertNotIn('model', config)
            self.assertIn('mcp_servers', config)

    def test_turnkey_mode_accepts_dashboard_credentials_outside_the_profile(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            home = self.write_home(tmp)
            inside = private_file(home, 'creds.json', {'publicKey': '02', 'privateKey': '03'})
            with self.assertRaises(Failure):
                subject.configure(configure_args(tmp, mode='turnkey', broker_credentials=str(inside),
                                                 organization_id='org-1'))
            outside = private_file(private, 'creds.json', {'publicKey': '02', 'privateKey': '03'})
            with self.assertRaises(Failure):
                subject.configure(configure_args(tmp, mode='turnkey', broker_credentials=str(outside)))
            subject.configure(configure_args(tmp, mode='turnkey', broker_credentials=str(outside),
                                             organization_id='org-1'))
            server = json.loads((home / 'config.yaml').read_text())['mcp_servers'][subject.SERVER]
            self.assertIn('--credentials', server['args'])
            self.assertEqual(server['args'][server['args'].index('--organization-id') + 1], 'org-1')
            # The private key is not copied into config.yaml.
            self.assertNotIn('03', json.dumps(server))

    def test_tk_secret_env_is_the_hermes_secret_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self.write_home(tmp)
            with self.assertRaises(Failure):
                subject.configure(configure_args(tmp, tk=str(home / 'missing-tk')))
            tk = home / 'tk'
            tk.write_text('')
            subject.configure(configure_args(tmp, tk=str(tk), tk_profile='hermes'))
            command = json.loads((home / 'config.yaml').read_text())['secrets']['command']
            self.assertTrue(command['enabled'])
            self.assertTrue(command['override_existing'])
            self.assertEqual(command['helper_timeout_seconds'], 30)
            self.assertIn(f'{tk} --profile hermes --message-format json secret env', command['command'])
            self.assertIn('--name-prefix hermes/', command['command'])
            self.assertIn('--property consensus=unilateral', command['command'])
            self.assertNotIn('TURNKEY_', command['command'])


class DistributionTests(unittest.TestCase):
    def test_root_skill_matches_the_bundled_skill(self):
        root = ROOT / 'skills' / 'secure-browser'
        bundled = ROOT / 'bundle' / 'secure-browser-mcp' / 'skills' / 'secure-browser'
        comparison = filecmp.dircmp(root, bundled)
        self.assertEqual(comparison.left_only + comparison.right_only + comparison.diff_files, [])
        for sub in comparison.subdirs.values():
            self.assertEqual(sub.left_only + sub.right_only + sub.diff_files, [])

    def test_turnkey_skills_have_frontmatter_and_resolvable_links(self):
        category = ROOT / 'skills' / 'turnkey'
        skills = sorted(p for p in category.rglob('SKILL.md'))
        self.assertGreaterEqual(len(skills), 5)
        link = re.compile(r'\]\(([^)#\s]+)(#[^)]*)?\)')
        for path in category.rglob('*.md'):
            text = path.read_text()
            if path.name == 'SKILL.md':
                self.assertTrue(text.startswith('---\n'), path)
                head = text.split('---', 2)[1]
                self.assertIn('\nname:', head, path)
                self.assertIn('\ndescription:', head, path)
            for target, _ in link.findall(text):
                if target.startswith(('http://', 'https://', 'mailto:')):
                    continue
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.exists(), f'{path}: dangling link {target}')
                self.assertIn(category.resolve(), resolved.parents, f'{path}: link escapes skills/turnkey')

    def test_manifest_lists_what_ships(self):
        manifest = (ROOT / 'distribution.yaml').read_text()
        for owned in ('SOUL.md', 'config.yaml', 'skills/', 'scripts/', 'bundle/', '.env.template'):
            self.assertIn(owned, manifest)
        self.assertNotIn('tk.example.json', manifest)
        self.assertFalse((ROOT / 'scripts' / 'tk_agents.py').exists())


if __name__ == '__main__':
    unittest.main()
