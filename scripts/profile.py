#!/usr/bin/env python3
"""Configure the Hermes distribution and launch the Secure Browser broker."""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVER = 'secure_browser'
# The broker's working tools. `list_network_requests` is a registered stub that
# returns not_implemented upstream, so it stays out of the allowlist.
TOOLS = ['list_secret_refs', 'navigate', 'snapshot', 'click', 'type_text',
         'fill_secret', 'await_fill']
BROKER_KEYS = ('TURNKEY_API_PUBLIC_KEY', 'TURNKEY_API_PRIVATE_KEY', 'TURNKEY_ORGANIZATION_ID')
# Hermes platforms that get only the broker's tools. Any platform not listed
# still loses the built-in shell, file, browser, and code tools through
# `agent.disabled_toolsets`, which Hermes applies after platform selection.
PLATFORMS = ('cli', 'photon', 'telegram', 'discord', 'slack', 'whatsapp', 'signal',
             'bluebubbles', 'matrix', 'mattermost', 'email', 'webhook', 'api_server')
DISABLED_TOOLSETS = ['terminal', 'file', 'browser', 'code_execution', 'computer_use',
                     'delegation']
# Passed from the host environment to the broker; nothing else crosses.
HOST_KEYS = ('HOME', 'PATH', 'TMPDIR', 'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR',
             'SBM_CHROME_PATH', 'SBM_HEADLESS', 'SBM_DASHBOARD_URL')
# `tk secret env` turns a secret named <prefix><VAR> into the variable VAR, so
# the prefix must end in a slash and the selector must be one static property.
# The patterns also keep shell metacharacters out of the secrets.command line.
TK_PROFILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
TK_NAME_PREFIX = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,127}/')
TK_PROPERTY = re.compile(r'[A-Za-z0-9_.-]{1,64}=[A-Za-z0-9_./:+@,-]{1,64}')


class Failure(Exception):
    """A stable error code for the operator; never carries secret material."""


def read_credentials(credentials, organization_id=None):
    """Load the broker's Turnkey API key from a private file.

    Two shapes are accepted: the profile's `broker.example.json` with the three
    TURNKEY_* keys, and the file the Turnkey dashboard downloads when an API key
    is created (`publicKey`/`privateKey`, no organization). The second needs
    `organization_id`.
    """
    if credentials is None:
        raise Failure('BROKER_CREDENTIALS_REQUIRED')
    path = Path(credentials)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise Failure('BROKER_FILE_MUST_BE_OWNED_AND_PRIVATE')
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise Failure('BROKER_CREDENTIALS_REQUIRED')
    if all(isinstance(data.get(k), str) and data[k].strip() for k in BROKER_KEYS):
        values = {k: data[k].strip() for k in BROKER_KEYS}
        if organization_id and organization_id != values['TURNKEY_ORGANIZATION_ID']:
            raise Failure('ORGANIZATION_ID_MISMATCH')
        return values
    public, private = data.get('publicKey'), data.get('privateKey')
    if (isinstance(public, str) and public.strip() and isinstance(private, str)
            and private.strip()):
        if not organization_id:
            raise Failure('ORGANIZATION_ID_REQUIRED')
        return {'TURNKEY_API_PUBLIC_KEY': public.strip(),
                'TURNKEY_API_PRIVATE_KEY': private.strip(),
                'TURNKEY_ORGANIZATION_ID': organization_id}
    raise Failure('BROKER_CREDENTIALS_REQUIRED')


def broker_environment(mode, credentials=None, organization_id=None):
    # Carry only the host basics required by Bun/Chrome, never model credentials.
    env = {k: v for k, v in os.environ.items() if k in HOST_KEYS}
    if mode == 'turnkey':
        env.update(read_credentials(credentials, organization_id))
        # Production endpoint fixed; no accidental export to a configured proxy.
        env['TURNKEY_API_BASE_URL'] = 'https://api.turnkey.com'
    elif mode != 'mock':
        raise Failure('INVALID_BROKER_MODE')
    return env


def tool_selection():
    """Config keys that leave the agent with the broker's tools only."""
    return {
        'platform_toolsets': {platform: [SERVER] for platform in PLATFORMS},
        'agent': {'disabled_toolsets': list(DISABLED_TOOLSETS)},
    }


def load_tk_config(path):
    """The tk.example.json shape: tk path, agent profile, name prefix, property."""
    config = json.loads(Path(path).read_text())
    if not isinstance(config, dict):
        raise Failure('INVALID_TK_CONFIG')
    tk = config.get('tk')
    if not isinstance(tk, str) or not Path(tk).is_absolute():
        raise Failure('INVALID_TK_PATH')
    for key, pattern, code in (('profile', TK_PROFILE, 'INVALID_TK_PROFILE'),
                               ('name_prefix', TK_NAME_PREFIX, 'INVALID_TK_NAME_PREFIX'),
                               ('property', TK_PROPERTY, 'INVALID_TK_PROPERTY')):
        value = config.get(key)
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise Failure(code)
    return config


def configuring_home():
    # The account database, not $HOME: `sudo` without -H and Hermes's own
    # terminal tool both rewrite HOME, and tk must find the registry of the
    # user that will run Hermes.
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        return Path.home()


def secrets_command(config, home):
    """Hermes `secrets.command` that turns <prefix><VAR> secrets into VAR=value.

    Hermes runs the command through `/bin/sh -c` with a scrubbed environment,
    so HOME is set explicitly for tk to find its profile registry. `tk secret
    env` prints one dotenv line per matching secret (default output, not JSON)
    and prints nothing, exit 1, code approval_required, if any of them needs an
    approval. It refuses values containing a newline, NUL, or single quote and
    single-quotes anything that is not a plain token, so `${...}` is never
    interpolated by Hermes's dotenv parser. Every secret under the prefix with
    the property lands in Hermes's environment, so the broker's TURNKEY_*
    credentials must never be imported under it.
    """
    command = [config['tk'], '--profile', config['profile'], '--non-interactive',
               'secret', 'env', '--name-prefix', config['name_prefix'],
               '--property', config['property']]
    return 'HOME=' + shlex.quote(str(home)) + ' ' + shlex.join(command)


def configure(args):
    home = Path(args.profile_home).expanduser().resolve()
    if not (home / 'distribution.yaml').is_file():
        raise Failure('INSTALL_PROFILE_FIRST')
    if bool(args.model) != bool(args.provider):
        raise Failure('MODEL_AND_PROVIDER_GO_TOGETHER')
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
        read_credentials(credential_path, args.organization_id)
        command += ['--credentials', str(credential_path)]
        if args.organization_id:
            command += ['--organization-id', args.organization_id]
    config = {}
    if args.model:
        config['model'] = {'default': args.model, 'provider': args.provider}
    config.update(tool_selection())
    config['mcp_servers'] = {SERVER: {
        'command': command[0], 'args': command[1:],
        'tools': {'include': TOOLS, 'resources': False, 'prompts': False},
        'sampling': {'enabled': False}, 'supports_parallel_tool_calls': False,
    }}
    if args.tk_config:
        tk_config = load_tk_config(Path(args.tk_config).expanduser().resolve())
        config['secrets'] = {'command': {
            'enabled': True,
            'command': secrets_command(tk_config, configuring_home()),
            'helper_timeout_seconds': 30, 'override_existing': True,
        }}
    (home / 'config.yaml').write_text(json.dumps(config, indent=2) + '\n')
    destination.write_text('Host paths configured; config.yaml is preserved by profile updates.\n')
    print('Profile configured. Install the bundled Bun dependencies before starting Hermes.')
    if not args.model:
        print('No model written: pick one with `hermes -p <profile> model` or set it in config.yaml.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('configure')
    setup.add_argument('--profile-home', required=True)
    setup.add_argument('--bun', required=True)
    setup.add_argument('--model', help='model id; omit to choose one in Hermes later')
    setup.add_argument('--provider', help='provider for --model')
    setup.add_argument('--mode', choices=['mock', 'turnkey'], required=True)
    setup.add_argument('--broker-credentials',
                       help='private JSON file: broker.example.json shape, or the dashboard download')
    setup.add_argument('--organization-id',
                       help='Turnkey organization for a dashboard credential file')
    setup.add_argument('--tk-config', help='JSON with tk, profile, name_prefix, property '
                       '(see tk.example.json); wires `tk secret env` in as Hermes secrets.command')
    broker = commands.add_parser('broker')
    broker.add_argument('--bun', required=True)
    broker.add_argument('--mode', choices=['mock', 'turnkey'], required=True)
    broker.add_argument('--credentials')
    broker.add_argument('--organization-id')
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            configure(args)
        else:
            env = broker_environment(args.mode, args.credentials, args.organization_id)
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
