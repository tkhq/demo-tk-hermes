# demo-tk-hermes

A [Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions) that lets a Hermes agent log into websites with credentials it never sees. Secrets live in Turnkey. The bundled [Secure Browser MCP](https://github.com/tkhq/secure-browser-mcp) owns a browser, exports a secret only to the page and field it was bound to at import, and the model gets back `{ filled: true }`. Exports that need a human go to the Turnkey dashboard for approval first.

Validated end to end on 2026-09-16: Hermes 0.21.3 on macOS, texting the agent over iMessage (Photon), a real Turnkey organization, and a pending export approved from the dashboard link the agent sent back.

What ships:

- `distribution.yaml`, `SOUL.md`, `config.yaml`, `.env.template`: the profile.
- `bundle/secure-browser-mcp/`: the broker source, tests, lockfile, and vendored Turnkey SDK tarballs at a pinned commit (`bundle/UPSTREAM.md`).
- `skills/secure-browser/`: the broker's agent skill, byte-identical to the bundled copy.
- `skills/turnkey/`: tk CLI skills for setting up the organization (tags, policies, secret imports, approvals), vendored from [turnkey-agent-skills](https://github.com/tkhq/turnkey-agent-skills) (`skills/turnkey/UPSTREAM.md`). The agent explains these commands; you run them.
- `scripts/profile.py`: writes host paths into `config.yaml`, launches the broker with a minimal environment, and wires the model token through `tk secret env`.
- `broker.example.json`, `tk.example.json`: the two operator-side config shapes; copies live outside the profile.

The agent gets the broker's seven tools and nothing else: no shell, file, or built-in browser tools, no MCP sampling, no parallel tool calls. This is a demo profile, not an OS sandbox. A host user with access to the credential file can still read it.

## Requirements

- [Hermes](https://hermes-agent.nousresearch.com/docs/getting-started/installation) 0.21 or later with a model configured.
- [Bun](https://bun.sh/docs/installation), Git, and Chrome, Chromium, Brave, or Edge.
- A Turnkey organization with Secrets enabled, and an API key for a non-root user the broker will run as.
- The [tk CLI](https://github.com/tkhq/tk) for organization setup and the optional model-token secret. The Turnkey sections need `secret env`, `session`, and the flag forms of `user create`, `user tag create`, and `policy create`, planned for tk 0.3.0. Until it ships, install a prerelease of [tk PR 44](https://github.com/tkhq/tk/pull/44); prerelease tags have the form `pr-44-<short sha>` and the PR's checks list the current one:

  ```sh
  curl --proto '=https' --tlsv1.2 -LsSf https://raw.githubusercontent.com/tkhq/tk/main/install.sh | TK_VERSION=pr-44-7d5a032 sh
  tk --version
  ```

No Python helper sits between Hermes and tk. `scripts/profile.py` only writes configuration and launches the browser broker.

## Install

```sh
hermes profile install https://github.com/tkhq/demo-tk-hermes.git --alias
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

Run these yourself in a terminal outside the agent. The agent can walk you through them from the `turnkey` skills, but it cannot run them. The pattern is the one in `skills/turnkey/tk-cli/references/agent-policy-patterns.md`: policies name user tags and secret properties, never ids. Placeholders are `REPLACE_WITH_*`; every id comes from a previous command's output.

A root profile for you. `tk profile create` generates a key pair locally and prints only the public key; register it on your root user in the Turnkey dashboard, then log in:

```sh
tk profile create --profile-name admin --organization-id REPLACE_WITH_ORG_UUID
# Dashboard: your root user -> API keys -> add the printed public key.
tk login --profile-name admin
tk --profile admin whoami
```

The `admin` profile is yours. Root bypasses every policy, so it is never the agent's or the broker's runtime credential.

Tags, and the human who approves:

```sh
tk --profile admin --message-format json user tag create --name agent
tk --profile admin --message-format json user tag create --name human-approver
tk --profile admin --message-format json user tag list
tk --profile admin --message-format json user update \
  --input-json '{"userId":"REPLACE_WITH_ROOT_USER_UUID","userTagIds":["REPLACE_WITH_HUMAN_APPROVER_TAG_UUID"]}'
```

The broker runs as a non-root user with the `agent` tag. Generate its key on the machine that runs Hermes (only the public key leaves it), and create the user:

```sh
tk profile create --profile-name agent --organization-id REPLACE_WITH_ORG_UUID
tk --profile admin --message-format json user create --user-name agent --tag-name agent --public-key REPLACE_WITH_AGENT_PUBLIC_KEY
tk login --profile-name agent
```

The `agent` profile's key file under `~/.config/turnkey/tk/api-keys/` is the broker credential for step 1 if you prefer it over a dashboard-issued key; record the agent's user id from the `user create` result either way.

Non-root users can do nothing until a policy allows it, with one exception: Turnkey default-allows a user managing its own API keys and authenticators. Policy 3 closes that, so a leaked agent key cannot register itself a permanent one. Policies 1 and 2 let agents export secrets by property, alone for `consensus=unilateral` (allow-always) and only with a human approval for `consensus=approval` (allow-once):

```sh
tk --profile admin --message-format json policy create --name agents-export-unilateral --effect allow \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_AGENT_TAG_UUID'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_EXPORT_SECRETS' && secret.static_properties['consensus'] == 'unilateral'"

tk --profile admin --message-format json policy create --name agents-export-with-approval --effect allow \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_AGENT_TAG_UUID')) && approvers.any(user, user.tags.contains('REPLACE_WITH_HUMAN_APPROVER_TAG_UUID'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_EXPORT_SECRETS' && secret.static_properties['consensus'] == 'approval'"

tk --profile admin --message-format json policy create --name agents-no-api-keys-or-authenticators --effect deny \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_AGENT_TAG_UUID'))" \
  --condition "activity.resource == 'CREDENTIAL'"
```

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

## Model API tokens from Turnkey

Hermes can read its provider token from Turnkey Secrets at startup through its native [command secret source](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/command). The command is `tk secret env`: it exports every secret whose name starts with a prefix and carries a chosen static property, and prints one dotenv line per secret. A secret named `agent/OPENROUTER_API_KEY` becomes the variable `OPENROUTER_API_KEY`. Hermes runs as the non-root `agent` user from the section above, whose only standing permission is to export those secrets. The `provisioning-agent-identity` skill under `skills/turnkey/` describes the same setup for an agent to walk you through.

### Import the provider token

Name the secret `<prefix>/<VARIABLE>` with the variable the provider expects, and give it exactly one `consensus` property. Import from a file or a pipe, never as a command-line argument. Keep browser credentials and Turnkey API private keys out of this prefix; anything under it becomes an environment variable in the Hermes process.

```sh
printf %s "$OPENROUTER_API_KEY" | tk --profile admin secret import agent/OPENROUTER_API_KEY --property consensus=unilateral
tk --profile agent secret env --name-prefix agent/ --property consensus=unilateral
```

The second command runs as the agent, not root, and must print exactly the variables Hermes needs. Secrets are immutable; to rotate the token, `tk --profile admin secret delete --name agent/OPENROUTER_API_KEY` and import the new value under the same name. Hermes selects secrets by name and property rather than by id, so whoever may delete and import under the prefix decides what Hermes loads; in this model that is only the root profile. A secret with `consensus=approval` in the selection makes `secret env` print nothing and exit 1 with code `approval_required`, so keep approval-gated secrets out of the startup prefix or approve them before starting Hermes.

### Wire it into Hermes

Copy `tk.example.json` outside the profile and set the absolute `tk` path, the agent profile name, the name prefix, and the property selector. The file holds no secret material.

```json
{
  "tk": "/absolute/path/to/tk",
  "profile": "agent",
  "name_prefix": "agent/",
  "property": "consensus=unilateral"
}
```

Add `--tk-config /absolute/path/to/tk-hermes.json` to the `configure` command. It writes this block, with `HOME` set to the home directory of the account running `configure` (from the account database, not `$HOME`, so `sudo` cannot bake in the wrong one), because Hermes runs the helper through `/bin/sh -c` with a scrubbed environment and tk needs it to find its profile registry. Run `configure` as the OS user that runs Hermes and owns the `agent` profile:

```yaml
secrets:
  command:
    enabled: true
    command: HOME=/home/you /absolute/path/to/tk --profile agent --non-interactive secret env --name-prefix agent/ --property consensus=unilateral
    helper_timeout_seconds: 30
    override_existing: true
```

`tk secret env` refuses values containing a newline, NUL, or single quote, and single-quotes any value with characters outside letters, digits, and `_./:+=@,-`, so `${...}` in a value is never interpolated. Each secret is one export activity, so keep the selection to the handful of tokens Hermes needs to fit the 30-second timeout.

**Hermes does not block startup when a command secret source fails.** A leftover shell or `.env` credential may remain usable after a failed export. For a strict Turnkey-only setup, remove duplicate provider credentials from the runtime before launching and verify the resulting provider configuration.

### Optional: session keys for the agent

With the steps above, the agent profile holds one long-lived API key. `tk session` replaces it with keys that expire, minted by a separate **provisioner** identity that can do nothing else and needs a human approval per mint. The agent generates each key pair itself and hands over only the public key. This is the `provisioning-session-agent` skill in turnkey-agent-skills.

On one laptop the provisioner is a second tk profile under the same OS user, which demonstrates the mechanics but not the isolation. In a real deployment the provisioner runs in its own container or host with its own credential store, and only public keys cross between the two.

Turnkey requires every user to hold one long-lived credential. The agent user already has one, its first API key, so it can serve as the anchor: run the loop below, then delete that first key with `tk --profile admin api-key delete --user-id REPLACE_WITH_AGENT_USER_UUID REPLACE_WITH_OLD_API_KEY_UUID` once a session key is active. A brand-new session agent is instead created with `--anchor-key`, which registers a never-expiring key whose private half is generated locally and discarded:

```sh
tk --profile admin user create --user-name agent --tag-name agent --public-key REPLACE_WITH_AGENT_PUBLIC_KEY --expires-in 4h --anchor-key
```

Either way, create the provisioner next:

```sh
tk profile create --profile-name provisioner --organization-id REPLACE_WITH_ORG_UUID
tk --profile admin user tag create --name provisioner
tk --profile admin user create --user-name provisioner --tag-name provisioner --public-key REPLACE_WITH_PROVISIONER_PUBLIC_KEY
tk login --profile-name provisioner
```

Policies 4 to 6 complete the six from the patterns reference. The provisioner may register API keys only with a human approver (allow-once), may do nothing else, and may not register a key on itself. Policy 6 is the one id-based policy: the target user's tags are not visible to the policy engine, so the only hard stop names the provisioner's own user id. Without it a self-mint goes pending instead of being denied.

```sh
tk --profile admin policy create --name provisioners-mint-agent-keys --effect allow \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_PROVISIONER_TAG_UUID')) && approvers.any(user, user.tags.contains('REPLACE_WITH_HUMAN_APPROVER_TAG_UUID'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_CREATE_API_KEYS_V2'"

tk --profile admin policy create --name provisioners-nothing-else --effect deny \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_PROVISIONER_TAG_UUID'))" \
  --condition "activity.type != 'ACTIVITY_TYPE_CREATE_API_KEYS_V2'"

tk --profile admin policy create --name provisioners-no-self-keys --effect deny \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_PROVISIONER_TAG_UUID'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_CREATE_API_KEYS_V2' && activity.params.user_id == 'REPLACE_WITH_PROVISIONER_USER_UUID'"
```

Now run the loop once. `request` prints the new public key and the agent's user id; `provision` submits the registration and reports `pending` with an activity id. Approve it in the Turnkey dashboard after checking that `userId` is the agent and `expiresIn` is what you asked for; policies can see the target user id but not its tags, and cannot see the lifetime at all. Re-running `provision` after approval reports the registered key and does not mint a second one. `activate` fails with `unauthorized` until then and leaves the profile unchanged.

```sh
tk session request --profile-name agent
tk --profile provisioner session provision --user-id REPLACE_WITH_AGENT_USER_UUID --public-key REPLACE_WITH_SESSION_PUBLIC_KEY --expires-in 4h
# Approve the activity, then run the same provision command again.
tk --profile provisioner session provision --user-id REPLACE_WITH_AGENT_USER_UUID --public-key REPLACE_WITH_SESSION_PUBLIC_KEY --expires-in 4h
tk session activate --profile-name agent
tk session status --profile-name agent
```

Nothing in `config.yaml` changes: `secrets.command` still names the `agent` profile, and `activate` repoints that profile at the new key and deletes the old generated key file. Hermes picks the new key up at its next start.

**Renewal.** `tk session status --profile-name agent --warn-before 90m` exits 0 while the key has more than 90 minutes left and exits 1 with code `session_expiring` inside the window, so it works as a cron or launchd check. A renewal job runs it on a schedule and, on `session_expiring`, runs `session request`, then `session provision` from the provisioner profile, and keeps re-running `provision` and `activate` on later ticks until the human approval lands and `activate` succeeds. `provision`, `activate`, and `status` are safe to repeat. `session request` refuses to run while a request is pending (pass `--replace` to discard it), so the job issues one request per renewal and then only re-runs `provision` and `activate`. The only state the job needs is the requested public key and user id, which are public. A mint left unapproved past expiry breaks the agent's next secret export until it is approved; that is the trade for holding no long-lived key. A Hermes cron job that runs `session status` with `--no-agent` and messages you only when a mint is pending keeps the loop quiet otherwise.

## Git and SSH signing

tk can also act as the SSH signing program for Git and as an SSH agent; see the SSH docs in the [tk repository](https://github.com/tkhq/tk). In a repository:

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

Hermes preserves your `config.yaml`, so host paths and the `secrets.command` line stay local; `--force-config` replaces it with the disabled template. Skills under `skills/` are replaced per top-level entry. Your copy of `tk.example.json` and your tk profiles live outside the profile and are not touched.

## Validation

```sh
python3 -m unittest discover -s tests -v
cd bundle/secure-browser-mcp && bun run typecheck && bun test
```

The Python suite covers config generation, both credential file shapes, environment separation, the tool selection, the `tk secret env` command line (tk path quoting, `HOME` derivation, rejected shell metacharacters), and that the vendored skills are intact. The bundled suite uses the local storefront on port 4173, including consensus and redaction tests. Live exports, session-key minting, and a live Hermes conversation are not part of the suites; the browser flow above was exercised by hand.

## License

MIT (see `LICENSE`). The vendored `skills/turnkey/` are Apache-2.0 from turnkey-agent-skills, with their license text alongside. The bundled Secure Browser MCP keeps whatever license upstream declares.

## References

- [Hermes profile distributions](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions)
- [Hermes MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference)
- [Hermes command secret source](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/command)
- [Secure Browser MCP](https://github.com/tkhq/secure-browser-mcp)
- [Turnkey agent skills](https://github.com/tkhq/turnkey-agent-skills)
- [tk CLI](https://github.com/tkhq/tk): `docs/secrets.md`, `docs/sessions.md`, and `docs/core.md` on the [PR 44](https://github.com/tkhq/tk/pull/44) branch
