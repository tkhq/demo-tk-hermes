# demo-tk-hermes

A private [Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions) with Turnkey secrets, Git/SSH signing guidance, and Secure Browser MCP bundled at a pinned commit.

- `distribution.yaml`, `SOUL.md`, and `skills/secure-browser/` package the agent profile.
- `bundle/secure-browser-mcp/` includes the broker source, tests, lockfile, and its upstream vendored Turnkey SDK dependencies. See `bundle/UPSTREAM.md` for provenance.
- `scripts/profile.py` configures absolute host paths after installation, wires `tk secret env` in as Hermes's native `secrets.command`, and launches the browser broker.
- Browser tools are restricted to the broker's eight tools. General browser, shell, file, and code-execution toolsets are not selected by default. MCP sampling and parallel calls are disabled.

This is a demo profile, not an OS sandbox or a deployed service. A host user or another process with access to the credential file can still read it. Model API tokens are resolved into Hermes's environment. Browser credentials are resolved inside the broker and filled by reference. Do not treat these as identical guarantees.

## Requirements

Install Hermes 0.21.3 or later with profile-distribution support, Python 3.9+, Bun, and Chrome/Chromium. Each user needs access to this private repository.

The Turnkey sections need a [`tk`](https://github.com/tkhq/tk) build with `secret env`, `session`, and the flag forms of `user create`, `user tag create`, and `policy create`. Those ship in tk 0.3.0; until it is released, install a prerelease of [tk PR 44](https://github.com/tkhq/tk/pull/44). Prerelease tags have the form `pr-44-<short sha>`; the PR's checks list the current one.

```sh
curl --proto '=https' --tlsv1.2 -LsSf https://raw.githubusercontent.com/tkhq/tk/main/install.sh | TK_VERSION=pr-44-7d5a032 sh
tk --version
```

No Python helper sits between Hermes and `tk`. `scripts/profile.py` only writes configuration and launches the browser broker.

Hermes is not installed on the machine used to author this demo. The profile contract was checked against upstream documentation; installation and a live model conversation still need validation on a Hermes host.

## Install the profile

```sh
hermes profile install git@github.com:tkhq/demo-tk-hermes.git --alias
```

This installs the profile as `tk-hermes`. The initial MCP configuration is disabled until you choose a backend and resolve host paths. It does not silently connect to a mock backend on missing production credentials.

```sh
cd ~/.hermes/profiles/tk-hermes/bundle/secure-browser-mcp
bun install --frozen-lockfile
```

The bundle does not depend on Git submodules or recursive clone behavior. Bun installs the pinned dependency graph on the recipient machine.

## Try mock browser mode

From a trusted terminal, using a model/provider already available to you:

```sh
python3 ~/.hermes/profiles/tk-hermes/scripts/profile.py configure \
  --profile-home ~/.hermes/profiles/tk-hermes \
  --bun "$(command -v bun)" \
  --model YOUR_MODEL_ID --provider openrouter \
  --mode mock
```

Set up the selected provider using your usual Hermes credentials, or add `--tk-config` as described under [Model API tokens from Turnkey](#model-api-tokens-from-turnkey) so Hermes reads the token from Turnkey. Start the mock storefront in another terminal:

```sh
cd ~/.hermes/profiles/tk-hermes/bundle/secure-browser-mcp
bun run demo:fixture
```

Then start the profile:

```sh
hermes -p tk-hermes chat
```

Ask it to list available credential references and log into `http://localhost:4173/login` using the matching mock reference. The demo storefront and credentials are synthetic. Mock mode removes all ambient Turnkey and model credentials from the broker environment. It needs no real Turnkey account.

The configure command initializes the profile once and refuses to overwrite an already-configured profile. To experiment with another setup, install another profile with `--name` and configure its directory. To inspect or edit an existing setup deliberately, use its `config.yaml`.

## Real Turnkey browser mode

Copy `broker.example.json` to an operator-controlled path **outside** the Hermes profile and agent workspace, fill its three fields in a trusted editor, and set mode `0600`. Never place values in chat or commit this file.

```sh
chmod 600 /absolute/private/broker.private.json
python3 ~/.hermes/profiles/tk-hermes/scripts/profile.py configure \
  --profile-home ~/.hermes/profiles/tk-hermes \
  --bun "$(command -v bun)" \
  --model YOUR_MODEL_ID --provider openrouter \
  --mode turnkey \
  --broker-credentials /absolute/private/broker.private.json
```

The broker wrapper rejects missing fields, non-private permissions, wrong ownership, and symlink credential files at launch. Configuration rejects a credential file under the profile. It constructs a limited child environment and fixes the API endpoint to `https://api.turnkey.com`. It does not inject the broker's API private key into Hermes's `secrets.command` output. This file/process separation is not protection against unrestricted host shell or filesystem access.

Import browser credentials with immutable bindings: `sbm:origin` is required; `sbm:url-pattern`, `sbm:selector`, and `sbm:fields` constrain the destination further. See the bundled broker README and threat model. Use a dedicated broker principal with policies limited to the intended secrets. Do not give it unrestricted export permission merely to make a demo succeed.

The model uses `list_secret_refs`, `navigate`, `snapshot`, and `fill_secret`. A gated fill returns `pending_approval`; the operator approves the Turnkey activity and the model uses `await_fill`. The broker rechecks the destination before filling. It does not expose script evaluation.

## Model API tokens from Turnkey

Hermes reads its provider token from Turnkey Secrets at startup, through its native `secrets.command` source. The command is `tk secret env`: it exports every secret whose name starts with a prefix and carries a chosen static property, and prints one dotenv line per secret. A secret named `agent/OPENROUTER_API_KEY` becomes the variable `OPENROUTER_API_KEY`. Hermes runs as a non-root Turnkey user whose only standing permission is to export those secrets.

The setup below follows two skills from [tkhq/turnkey-agent-skills](https://github.com/tkhq/turnkey-agent-skills) ([PR 26](https://github.com/tkhq/turnkey-agent-skills/pull/26)): `provisioning-agent-identity` for the tags, agent user, policies, and secrets, and `provisioning-session-agent` for short-lived keys. Both are written for an agent to run. Once step 1 gives you a root profile, you can install the skills and ask a coding agent to "run provisioning-agent-identity against the admin profile" instead of typing steps 2 to 4 yourself. The commands are shown here so you can see what the skill does and check its work. The policy vocabulary (allow-always, allow-once, tags `agent`, `provisioner`, `human-approver`, and the `consensus` secret property) is explained in the skills repo's `references/agent-policy-patterns.md`.

Placeholders are `REPLACE_WITH_*`; every id comes from a previous command's output. Never paste a private key or secret value into chat or into this repo.

### 1. A root profile for you

`tk profile create` generates a keypair locally and prints only the public key. Register that public key as an API key on your root user in the Turnkey dashboard (create an organization first if you do not have one), then log in.

```sh
tk profile create --profile-name admin --organization-id REPLACE_WITH_ORG_UUID
# Dashboard: your root user -> API keys -> add the printed public key.
tk login --profile-name admin
tk --profile admin whoami
```

The `admin` profile is yours. It is never used as Hermes's runtime credential, and root bypasses every policy, so keep it out of the agent's process.

### 2. Tags and the agent user

Create the tags once and record their ids. Tag yourself as the human approver so approval policies name a tag rather than root.

```sh
tk --profile admin user tag create --name agent
tk --profile admin user tag create --name human-approver
tk --profile admin user update --input-json '{"userId":"REPLACE_WITH_ROOT_USER_UUID","userTagIds":["REPLACE_WITH_HUMAN_APPROVER_TAG_UUID"]}'
```

Generate the agent's credential on the machine that runs Hermes, as the OS user that runs Hermes. Only the public key leaves that machine.

```sh
tk profile create --profile-name agent --organization-id REPLACE_WITH_ORG_UUID
tk --profile admin user create --user-name agent --tag-name agent --public-key REPLACE_WITH_AGENT_PUBLIC_KEY
tk login --profile-name agent
```

Record the agent's user id from the `user create` result. Skip to step 4 if you plan to move the agent onto session keys straight away; `provisioning-session-agent` recreates the user with `--anchor-key`.

### 3. The agent's policies

Non-root users can do nothing until a policy allows it, with one exception: Turnkey default-allows a user managing its own API keys and authenticators. Policy 3 closes that, so a leaked agent key cannot register itself a permanent one. Policies 1 and 2 let agents export secrets by property, alone for `consensus=unilateral` (allow-always) and only with a human approval for `consensus=approval` (allow-once).

```sh
tk --profile admin policy create --name agents-export-unilateral --effect allow \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_AGENT_TAG_UUID'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_EXPORT_SECRETS' && secret.static_properties['consensus'] == 'unilateral'"

tk --profile admin policy create --name agents-export-with-approval --effect allow \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_AGENT_TAG_UUID')) && approvers.any(user, user.tags.contains('REPLACE_WITH_HUMAN_APPROVER_TAG_UUID'))" \
  --condition "activity.type == 'ACTIVITY_TYPE_EXPORT_SECRETS' && secret.static_properties['consensus'] == 'approval'"

tk --profile admin policy create --name agents-no-api-keys-or-authenticators --effect deny \
  --consensus "approvers.any(user, user.tags.contains('REPLACE_WITH_AGENT_TAG_UUID'))" \
  --condition "activity.resource == 'CREDENTIAL'"
```

### 4. Import the provider token

Name the secret `<prefix>/<VARIABLE>` with the variable the provider expects, and give it exactly one `consensus` property. Import from a file or a pipe, never as a command-line argument. Keep browser credentials and Turnkey API private keys out of this prefix; anything under it becomes an environment variable in the Hermes process.

```sh
printf %s "$OPENROUTER_API_KEY" | tk --profile admin secret import agent/OPENROUTER_API_KEY --property consensus=unilateral
tk --profile agent secret env --name-prefix agent/ --property consensus=unilateral
```

The second command runs as the agent, not root, and must print exactly the variables Hermes needs. Secrets are immutable; to rotate the token, `tk --profile admin secret delete --name agent/OPENROUTER_API_KEY` and import the new value under the same name. A secret with `consensus=approval` in the selection makes `secret env` print nothing and exit 1 with code `approval_required`, so keep approval-gated secrets out of the startup prefix or approve them before starting Hermes.

### 5. Wire it into Hermes

Copy `tk.example.json` outside the profile and set the absolute `tk` path, the agent profile name, the name prefix, and the property selector. The file holds no secret material.

```json
{
  "tk": "/absolute/path/to/tk",
  "profile": "agent",
  "name_prefix": "agent/",
  "property": "consensus=unilateral"
}
```

Add this flag to the initial configure command:

```sh
--tk-config /absolute/path/to/tk-hermes.json
```

`configure` then writes this block, with `HOME` set to the configuring user's home because Hermes runs the helper through `/bin/sh -c` with a scrubbed environment and `tk` needs it to find its profile registry:

```yaml
secrets:
  command:
    enabled: true
    command: HOME=/home/you /absolute/path/to/tk --profile agent secret env --name-prefix agent/ --property consensus=unilateral
    helper_timeout_seconds: 30
    override_existing: true
```

`tk secret env` refuses values containing a newline, NUL, or single quote and single-quotes anything that is not a plain token, so `${...}` in a value is never interpolated. Each secret is one export activity, so keep the selection to the handful of tokens Hermes needs to fit the 30-second timeout.

**Hermes does not block startup when a command secret source fails.** A leftover shell or `.env` credential may remain usable after a failed export. For a strict Turnkey-only demo, remove duplicate provider credentials from the runtime before launching and verify the resulting provider configuration.

### Optional: session keys for the agent

With the steps above, the agent profile holds one long-lived API key. `tk session` replaces it with keys that expire, minted by a separate **provisioner** identity that can do nothing else and needs a human approval per mint. The agent generates each keypair itself and hands over only the public key. This is the `provisioning-session-agent` skill.

On one laptop the provisioner is a second `tk` profile under the same OS user, which demonstrates the mechanics but not the isolation. In a real deployment the provisioner runs in its own container or host with its own credential store, and only public keys cross between the two.

Turnkey requires every user to hold one long-lived credential, so a session-key agent is created with `--anchor-key`: a never-expiring key whose private half is generated locally and discarded. Recreate the agent user that way (delete the step 2 user first with `tk --profile admin user delete REPLACE_WITH_AGENT_USER_UUID`), then create the provisioner.

```sh
tk profile create --profile-name agent --organization-id REPLACE_WITH_ORG_UUID
tk --profile admin user create --user-name agent --tag-name agent --public-key REPLACE_WITH_AGENT_PUBLIC_KEY --expires-in 4h --anchor-key
tk login --profile-name agent

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

Now run the loop once. `request` prints the new public key and the agent's user id; `provision` submits the registration and reports `pending` with an activity id. Approve it in the Turnkey mobile app or dashboard after checking that `userId` is the agent and `expiresIn` is what you asked for, since neither is visible to policies. Re-running `provision` after approval reports the registered key and does not mint a second one. `activate` fails with `unauthorized` until then and leaves the profile unchanged.

```sh
tk session request --profile-name agent
tk --profile provisioner session provision --user-id REPLACE_WITH_AGENT_USER_UUID --public-key REPLACE_WITH_SESSION_PUBLIC_KEY --expires-in 4h
# Approve the activity on your phone, then run the same provision command again.
tk --profile provisioner session provision --user-id REPLACE_WITH_AGENT_USER_UUID --public-key REPLACE_WITH_SESSION_PUBLIC_KEY --expires-in 4h
tk session activate --profile-name agent
tk session status --profile-name agent
```

Nothing in `config.yaml` changes: `secrets.command` still names the `agent` profile, and `activate` repoints that profile at the new key and deletes the old generated key file. Hermes picks the new key up at its next start.

**Renewal.** `tk session status --profile-name agent --warn-before 90m` exits 0 while the key has more than 90 minutes left and exits 1 with code `session_expiring` inside the window, so it works as a cron or launchd check. A renewal job runs it on a schedule and, on `session_expiring`, runs `session request`, then `session provision` from the provisioner profile, and keeps re-running `provision` and `activate` on later ticks until the human approval lands and `activate` succeeds. Every one of those commands is safe to repeat, and the only state the job needs is the requested public key and user id, which are public. A mint left unapproved past expiry breaks the agent's next secret export until it is approved; that is the trade for holding no long-lived key. A Hermes cron job that runs `session status` with `--no-agent` and messages you only when a mint is pending keeps the loop quiet otherwise.

## Git and SSH signing

Use the existing [tk signing integration](https://github.com/tkhq/demo-tk-tact#git-signing-and-ssh). `tk`'s SSH configuration is separate from its named secret-export profiles.

For a selected repository, after configuring the SSH identity:

```sh
git config --local gpg.format ssh
git config --local gpg.ssh.program /absolute/path/to/tk
git config --local user.signingkey "key::$(/absolute/path/to/tk ssh public-key)"
git config --local commit.gpgsign true
git config --local tag.gpgsign true
```

For SSH authentication, run `tk ssh agent start` and set `SSH_AUTH_SOCK` to its socket before starting the relevant process. Register the public key with the destination service. Git/SSH currently reports approval-required errors instead of resuming the original signing call.

This profile defaults to browser tasks. Enabling terminal/file toolsets for coding is an operator choice and broadens access to host credentials. For a combined coding/browser deployment, isolate the broker and credential state from the coding runtime; do not add a generic shell tool to this profile and claim the same browser-secret boundary.

## Update

```sh
hermes profile update tk-hermes
```

The manifest includes `scripts/`, `bundle/`, and `tk.example.json` in distribution-owned content. Hermes normally preserves customized `config.yaml`; host paths and the `secrets.command` line remain local. Re-run `bun install --frozen-lockfile` in the bundle after an update. Do not use `--force-config` unless you intend to replace your configured host paths with the disabled template. Your copy of `tk.example.json` and your `tk` profiles live outside the profile and are not touched by updates.

## Validation

```sh
python3 -m unittest discover -s tests -v
cd bundle/secure-browser-mcp
bun run typecheck
bun test
```

The Python suite covers profile generation, explicit backend selection, credential-file checks, environment separation, and the `secrets.command` line written for `tk secret env`. The bundled browser suite uses a local synthetic storefront, including consensus/redaction tests. Its default fixture port is 4173; an existing process on that port must be handled by its owner. During author validation, an isolated test copy changed fixture URLs and bindings to 14173 without altering the shipped bundle.

Live Turnkey exports, session-key minting, and a Hermes model conversation are not tested by these suites.

## References

- [Hermes profile distributions](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions)
- [Hermes command secret source](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/command)
- [Hermes MCP configuration](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md)
- [Secure Browser MCP](https://github.com/tkhq/secure-browser-mcp)
- [tk](https://github.com/tkhq/tk): `docs/secrets.md`, `docs/sessions.md`, and `docs/core.md` on the [PR 44](https://github.com/tkhq/tk/pull/44) branch
- [Turnkey agent skills](https://github.com/tkhq/turnkey-agent-skills): `provisioning-agent-identity`, `provisioning-session-agent`, and `references/agent-policy-patterns.md` ([PR 26](https://github.com/tkhq/turnkey-agent-skills/pull/26))
