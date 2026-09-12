#!/usr/bin/env python3
"""Configure the Hermes distribution and launch its credential helpers."""
import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import sys

from tk_agents import Failure, export_secret, load_config

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ['list_secret_refs', 'navigate', 'snapshot', 'click', 'type_text',
         'fill_secret', 'await_fill', 'list_network_requests']
BROKER_KEYS = ('TURNKEY_API_PUBLIC_KEY', 'TURNKEY_API_PRIVATE_KEY', 'TURNKEY_ORGANIZATION_ID')


def broker_environment(mode, credentials=None):
    # Carry only the host basics required by Bun/Chrome, never model credentials.
    env = {k: v for k, v in os.environ.items() if k in
           ('HOME', 'PATH', 'TMPDIR', 'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR',
            'SBM_CHROME_PATH', 'SBM_HEADLESS')}
    if mode == 'turnkey':
        if credentials is None:
            raise Failure('BROKER_CREDENTIALS_REQUIRED')
        path = Path(credentials)
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise Failure('BROKER_FILE_MUST_BE_OWNED_AND_PRIVATE')
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or any(not isinstance(data.get(k), str)
                                             or not data[k].strip() for k in BROKER_KEYS):
            raise Failure('BROKER_CREDENTIALS_REQUIRED')
        env.update({k: data[k] for k in BROKER_KEYS})
        # Production endpoint fixed; no accidental export to a configured proxy.
        env['TURNKEY_API_BASE_URL'] = 'https://api.turnkey.com'
    elif mode != 'mock':
        raise Failure('INVALID_BROKER_MODE')
    return env


def secret_output(path):
    config = load_config(path)
    rows = []
    for alias in config['secrets']:
        if alias.startswith('TURNKEY_'):
            raise Failure('BROKER_CREDENTIALS_NOT_MODEL_SECRETS')
        value = export_secret(config, alias)
        # dotenv interpolation is not appropriate for arbitrary payloads. This
        # helper is for provider tokens, not browser passwords or JSON bundles.
        if any(c in value for c in ('\n', '\r', '\0', '${')):
            raise Failure('UNSUPPORTED_TOKEN_VALUE')
        rows.append(alias + '=' + json.dumps(value, ensure_ascii=False))
    return '\n'.join(rows) + '\n'


def configure(args):
    home = Path(args.profile_home).expanduser().resolve()
    if not (home / 'distribution.yaml').is_file():
        raise Failure('INSTALL_PROFILE_FIRST')
    local = home / 'local'
    local.mkdir(mode=0o700, exist_ok=True)
    destination = local / 'configured'
    if destination.exists():
        raise Failure('PROFILE_ALREADY_CONFIGURED')
    # Store relocatable content in the distribution, then resolve host paths
    # only after installation. Profile updates preserve config.yaml by default.
    runner = home / 'scripts' / 'profile.py'
    command = [sys.executable, str(runner), 'broker', '--bun', str(Path(args.bun).resolve()),
               '--mode', args.mode]
    if args.mode == 'turnkey':
        if not args.broker_credentials:
            raise Failure('BROKER_CREDENTIALS_REQUIRED')
        credential_path = Path(args.broker_credentials).expanduser().resolve()
        if home == credential_path or home in credential_path.parents:
            raise Failure('KEEP_BROKER_CREDENTIALS_OUTSIDE_PROFILE')
        broker_environment('turnkey', credential_path)
        command += ['--credentials', str(credential_path)]
    config = {
        'model': {'default': args.model, 'provider': args.provider},
        'toolsets': ['mcp-secure_browser'],
        'mcp_servers': {'secure_browser': {
            'command': command[0], 'args': command[1:],
            'tools': {'include': TOOLS, 'resources': False, 'prompts': False},
            'sampling': {'enabled': False}, 'supports_parallel_tool_calls': False,
        }},
    }
    if args.tk_config:
        path = str(Path(args.tk_config).expanduser().resolve())
        load_config(path)
        config['secrets'] = {'command': {
            'enabled': True,
            'command': shlex.join([sys.executable, str(runner), 'secrets', '--config', path]),
            'helper_timeout_seconds': 30, 'override_existing': True,
        }}
    (home / 'config.yaml').write_text(json.dumps(config, indent=2) + '\n')
    destination.write_text('Host paths configured; config.yaml is preserved by profile updates.\n')
    print('Profile configured. Install the bundled Bun dependencies before starting Hermes.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('configure')
    setup.add_argument('--profile-home', required=True)
    setup.add_argument('--bun', required=True)
    setup.add_argument('--model', required=True)
    setup.add_argument('--provider', default='openrouter')
    setup.add_argument('--mode', choices=['mock', 'turnkey'], required=True)
    setup.add_argument('--broker-credentials')
    setup.add_argument('--tk-config')
    broker = commands.add_parser('broker')
    broker.add_argument('--bun', required=True)
    broker.add_argument('--mode', choices=['mock', 'turnkey'], required=True)
    broker.add_argument('--credentials')
    secrets = commands.add_parser('secrets')
    secrets.add_argument('--config', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            configure(args)
        elif args.command == 'secrets':
            sys.stdout.write(secret_output(args.config))
        else:
            env = broker_environment(args.mode, args.credentials)
            bun = str(Path(args.bun).resolve())
            os.chdir(ROOT / 'bundle' / 'secure-browser-mcp')
            os.execve(bun, [bun, 'run', 'src/index.ts'], env)
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError):
        print('PROFILE_CONFIGURATION_ERROR', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
