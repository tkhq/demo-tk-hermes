# demo-tk-hermes

A private [Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions) that lets a Hermes agent log into websites with credentials it never sees. Secrets live in Turnkey. The bundled [Secure Browser MCP](https://github.com/tkhq/secure-browser-mcp) owns a browser, exports a secret only to the page and field it was bound to at import, and the model gets back `{ filled: true }`. Exports that need a human go to the Turnkey dashboard for approval first.

Validated end to end on 2026-09-16: Hermes 0.21.3 on macOS, texting the agent over iMessage (Photon), a real Turnkey organization, and a pending export approved from the dashboard link the agent sent back.

What ships:

- `distribution.yaml`, `SOUL.md`, `config.yaml`, `.env.template`: the profile.
- `bundle/secure-browser-mcp/`: the broker source, tests, lockfile, and vendored Turnkey SDK tarballs at a pinned commit (`bundle/UPSTREAM.md`).
- `skills/secure-browser/`: the broker's agent skill, byte-identical to the bundled copy.
- `skills/turnkey/`: tk CLI skills for setting up the organization (tags, policies, secret imports, approvals), vendored from [turnkey-agent-skills](https://github.com/tkhq/turnkey-agent-skills) (`skills/turnkey/UPSTREAM.md`). The agent explains these commands; you run them.
- `scripts/profile.py`: writes host paths into `config.yaml`, launches the broker with a minimal environment, and wires the model token through `tk secret env`.

The agent gets the broker's seven tools and nothing else: no shell, file, or built-in browser tools, no MCP sampling, no parallel tool calls. This is a demo profile, not an OS sandbox. A host user with access to the credential file can still read it.

## Requirements

- [Hermes](https://hermes-agent.nousresearch.com/docs/getting-started/installation) 0.21 or later with a model configured.
- [Bun](https://bun.sh/docs/installation), Git, and Chrome, Chromium, Brave, or Edge.
- A Turnkey organization with Secrets enabled, and an API key for a non-root user the broker will run as.
- The [tk CLI](https://github.com/tkhq/tk) 0.2.0 or later for organization setup and the optional model-token secret. `tk secret env`, `tk policy create --name`, and `tk user create --user-name` come from [tk PR #44](https://github.com/tkhq/tk/pull/44) until it merges; build that branch with `cargo build -p tk --bin tk` if your tk lacks them.

## Install

```sh
hermes profile install git@github.com:tkhq/demo-tk-hermes.git --alias
cd ~/.hermes/profiles/tk-hermes/bundle/secure-browser-mcp
bun install --frozen-lockfile
```

The profile installs as `tk-hermes`. Its MCP entry ships disabled until you configure a backend.

## Try it with mock secrets

No Turnkey account needed. Configure the profile in mock mode. Pass `--model` and `--provider` together to pin a model, or leave both out and pick one afterwards with `hermes -p tk-hermes model`. Either way the profile needs its own provider login (`hermes -p tk-hermes auth add <provider>` or `/login` in chat); a new profile does not inherit the default profile's credentials.

```sh
python3 ~/.hermes/profiles/tk-hermes/scripts/profile.py configure \
  --profile-home ~/.hermes/profiles/tk-hermes \
  --bun "$(command -v bun)" \
  --mode mock
```

Start the demo storefront in another terminal and leave it running:

```sh
cd ~/.hermes/profiles/tk-hermes/bundle/secure-browser-mcp
bun run demo:fixture
```

Then:

```sh
hermes -p tk-hermes chat
```

Ask it to list the available credential references and log into `http://localhost:4173/login` with the matching one. The response should report `backend: "mock"`. Mock mode removes every Turnkey and model credential from the broker's environment.

`configure` runs once and refuses to overwrite a configured profile. For a second setup, install the profile again under another `--name`. To change an existing setup, edit its `config.yaml`.

## Use real Turnkey secrets

### 1. Configure the broker

Create an API key for the broker's user in the Turnkey dashboard and keep the downloaded `turnkey-api-credentials-<timestamp>.json` **outside** the profile and the agent's workspace with mode `0600`. The file carries the key pair; the organization comes from the flag:

```sh
chmod 600 /absolute/private/turnkey-api-credentials-123.json
python3 ~/.hermes/profiles/tk-hermes/scripts/profile.py configure \
  --profile-home ~/.hermes/profiles/tk-hermes \
  --bun "$(command -v bun)" \
  --mode turnkey \
  --broker-credentials /absolute/private/turnkey-api-credentials-123.json \
  --organization-id "$ORG_ID"
```

`broker.example.json` shows the other accepted shape, with the three `TURNKEY_*` fields inside the file. At launch the broker wrapper rejects a missing field, a group- or world-readable file, a file owned by someone else, or a symlink. It fixes the API endpoint to `https://api.turnkey.com`, passes through only `HOME`, `PATH`, `TMPDIR`, display variables, `SBM_CHROME_PATH`, `SBM_HEADLESS`, and `SBM_DASHBOARD_URL`, and never writes the private key into `config.yaml`.

To watch the browser on a desktop, add `SBM_HEADLESS: "false"` under the server's `env` in `config.yaml`. If your browser is somewhere unusual, add `SBM_CHROME_PATH`.

### 2. Set up the organization with tk

Run these yourself, as an admin profile, in a terminal outside the agent. The agent can walk you through them from the `turnkey` skills, but it cannot run them. The pattern is the one in `skills/turnkey/tk-cli/references/agent-policy-patterns.md`: policies name user tags and secret properties, never ids.

Tags, and the human who approves:

```sh
tk --profile admin --message-format json user tag create --name agent
tk --profile admin --message-format json user tag create --name human-approver
tk --profile admin --message-format json user tag list
tk --profile admin --message-format json user update \
  --input-json '{"userId":"YOUR_USER_UUID","userTagIds":["HUMAN_APPROVER_TAG"]}'
```

The broker's user gets the `agent` tag. Then the two export policies:

```sh
tk --profile admin --message-format json policy create --name agents-export-unilateral --effect allow \
  --consensus "approvers.any(user, user.tags.contains('AGENT_TAG'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_EXPORT_SECRETS' && secret.static_properties['consensus'] == 'unilateral'"

tk --profile admin --message-format json policy create --name agents-export-with-approval --effect allow \
  --consensus "approvers.any(user, user.tags.contains('AGENT_TAG')) && approvers.any(user, user.tags.contains('HUMAN_APPROVER_TAG'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_EXPORT_SECRETS' && secret.static_properties['consensus'] == 'approval'"
```

Add `agents-no-api-keys-or-authenticators` from the same reference so the broker cannot mint itself a credential.

### 3. Import a login secret

Bindings are static properties on the secret. `sbm:origin` is required; `sbm:url-pattern` and `sbm:selector` narrow the destination. Properties are immutable, so open the target page first and confirm the field is in the main frame (cross-origin iframe fields, including embedded Stripe Elements, are unsupported). Put the password in a file the agent cannot read; never pass it as an argument.

```sh
tk --profile admin --message-format json secret import northwind-login \
  --property consensus=approval \
  --property sbm:origin=https://portal.example.com \
  --property sbm:url-pattern='/login*' \
  --property sbm:selector='input#password' \
  --from-file "$SECRET_INPUT_FILE"
```

`consensus=approval` is what makes the fill pause for a human. Use `consensus=unilateral` for a secret the agent may use alone. A secret that fills several fields at once (a card's number, expiry, and CVC) is one JSON value with `sbm:fields` mapping payload keys to selectors; see the broker README in the bundle.

### 4. Run the fill

In `hermes -p tk-hermes chat`, or over a messaging app (below), ask the agent to sign in. The flow is `list_secret_refs`, `navigate`, `snapshot`, `fill_secret`. For an approval-gated secret `fill_secret` returns `pending_approval` plus `approval_url`, a link of the form `https://app.turnkey.com/dashboard/v2/activities/<activity id>`. The agent sends you that link verbatim; approve the activity in the dashboard, tell the agent, and it calls `await_fill`. The broker rechecks the destination before injecting. `SBM_DASHBOARD_URL` overrides the dashboard base when you are not on production.

## Run it from a messaging app

The profile has its own gateway. Put the platform credentials in the profile's `.env` (see `.env.EXAMPLE`, written at install) and start it:

```sh
hermes -p tk-hermes gateway start
```

For iMessage through Photon, set `PHOTON_PROJECT_ID`, `PHOTON_PROJECT_SECRET`, and `PHOTON_ALLOWED_USERS`. A shared free-tier Photon line can only reply to a number that texted first, so start the conversation from your phone. Telegram works the same way with `TELEGRAM_BOT_TOKEN`.

If your default profile already runs a gateway with the same line or bot, turn on `gateway.multiplex_profiles: true` in the default profile's `config.yaml` and add a `gateway.profile_routes` entry for the chat that should reach `tk-hermes`. See [multi-profile gateways](https://hermes-agent.nousresearch.com/docs/user-guide/multi-profile-gateways).

Gateway sessions use the same `platform_toolsets` as the CLI: only the broker's tools. Hermes's built-in browser and shell tools stay disabled through `agent.disabled_toolsets`, which Hermes applies after platform selection.

## Optional: model API token from Turnkey

Store the model token as a Turnkey secret named `hermes/<PROVIDER_VAR>` with `consensus=unilateral`, readable by a tk profile that holds a non-root key:

```sh
tk --profile admin --message-format json secret import hermes/OPENROUTER_API_KEY \
  --property consensus=unilateral --from-file "$TOKEN_FILE"
```

Then pass `--tk /absolute/path/to/tk` (and `--tk-profile hermes` if the profile is not called `hermes`) to `configure`. Hermes runs `tk secret env --name-prefix hermes/ --property consensus=unilateral` at startup as its [command secret source](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/command), with a 30-second timeout and `override_existing`. Keep only provider tokens under the `hermes/` prefix; the broker's Turnkey key never goes through this path.

Hermes does not block startup when the command fails, so an older token in the shell or `.env` can stay in use. Remove duplicates for a strict Turnkey-only setup.

## Git and SSH signing

Use the existing [tk signing integration](https://github.com/tkhq/demo-tk-tact#git-signing-and-ssh). In a repository:

```sh
git config --local gpg.format ssh
git config --local gpg.ssh.program /absolute/path/to/tk
git config --local user.signingkey "key::$(/absolute/path/to/tk ssh public-key)"
git config --local commit.gpgsign true
git config --local tag.gpgsign true
```

For SSH authentication, run `tk ssh agent start` and point `SSH_AUTH_SOCK` at its socket. Enabling a terminal toolset for coding work is an operator choice that broadens what the agent can reach; keep it out of this profile if you want the browser-secret boundary described above.

## Update

```sh
hermes profile update tk-hermes
cd ~/.hermes/profiles/tk-hermes/bundle/secure-browser-mcp && bun install --frozen-lockfile
```

Hermes preserves your `config.yaml`; `--force-config` replaces it with the disabled template. Skills under `skills/` are replaced per top-level entry.

## Validation

```sh
python3 -m unittest discover -s tests -v
cd bundle/secure-browser-mcp && bun run typecheck && bun test
```

The Python suite covers config generation, both credential file shapes, environment separation, the tool selection, the `tk secret env` wiring, and that the vendored skills are intact. The bundled suite uses the local storefront on port 4173, including consensus and redaction tests. Live exports and a live Hermes conversation are not part of the suites; the flow above was exercised by hand.

## References

- [Hermes profile distributions](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions)
- [Hermes MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference)
- [Hermes command secret source](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/command)
- [Secure Browser MCP](https://github.com/tkhq/secure-browser-mcp)
- [Turnkey agent skills](https://github.com/tkhq/turnkey-agent-skills)
- [tk CLI](https://github.com/tkhq/tk)
