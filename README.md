# demo-tk-hermes

A private [Hermes profile distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions) with Turnkey secrets, Git/SSH signing guidance, and Secure Browser MCP bundled at a pinned commit.

- `distribution.yaml`, `SOUL.md`, and `skills/secure-browser/` package the agent profile.
- `bundle/secure-browser-mcp/` includes the broker source, tests, lockfile, and its upstream vendored Turnkey SDK dependencies. See `bundle/UPSTREAM.md` for provenance.
- `scripts/profile.py` configures absolute host paths after installation, supplies model API tokens through Hermes's native `secrets.command` interface, and launches the browser broker.
- Browser tools are restricted to the broker's eight tools. General browser, shell, file, and code-execution toolsets are not selected by default. MCP sampling and parallel calls are disabled.

This is a demo profile, not an OS sandbox or a deployed service. A host user or another process with access to the credential file can still read it. Model API tokens are resolved into Hermes's environment. Browser credentials are resolved inside the broker and filled by reference. Do not treat these as identical guarantees.

## Requirements

Install Hermes with profile-distribution support, Python 3.9+, Bun, and Chrome/Chromium. The optional model-secret helper requires a `tk` build supporting `secret export --message-format json` and named profiles (checked against `a7baa8c461c6ed14c142a052a858353587b4e45a`). Each user needs access to this private repository.

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

Set up the selected provider using your usual Hermes credentials, or use the Turnkey helper below during configuration. Start the mock storefront in another terminal:

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

## Optional: model API token from tk

Copy `tk.example.json` outside the profile, set an absolute `tk` path, a named profile, and the model token's secret UUID. Rename `OPENAI_API_KEY` to the provider's actual variable, for example `OPENROUTER_API_KEY`. Include only provider tokens, never browser credentials or Turnkey API private keys.

Add this flag to the initial configure command:

```sh
--tk-config /absolute/private/model-tk.json
```

This enables Hermes's native command secret source. The helper calls `tk` with an explicit profile, resolves the complete result before printing any dotenv output, and discards raw errors. Newlines, NULs, and dotenv interpolation expressions are rejected because this path is for tokens, not arbitrary secret payloads.

The source runs at startup with a 30-second Hermes timeout and overrides existing values on successful resolution. **Hermes does not block startup when a command secret source fails.** An existing shell/.env credential may remain usable after a pending approval or export failure. For a strict Turnkey-only demo, remove duplicate provider credentials from the runtime before launching and verify the resulting provider configuration. `tk` persists pending export state; approve and restart to resume. Keep the pilot to one model token to fit the timeout.

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

The manifest includes `scripts/` and `bundle/` in distribution-owned content. Hermes normally preserves customized `config.yaml`; host paths remain local. Re-run `bun install --frozen-lockfile` in the bundle after an update. Do not use `--force-config` unless you intend to replace your configured host paths with the disabled template.

## Validation

```sh
python3 -m unittest discover -s tests -v
cd bundle/secure-browser-mcp
bun run typecheck
bun test
```

The Python suite covers profile generation, explicit backend selection, credential-file checks, environment separation, and dotenv output. The bundled browser suite uses a local synthetic storefront, including consensus/redaction tests. Its default fixture port is 4173; an existing process on that port must be handled by its owner. During author validation, an isolated test copy changed fixture URLs and bindings to 14173 without altering the shipped bundle.

Live Turnkey exports and a Hermes model conversation are not tested by these suites.

## References

- [Hermes profile distributions](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions)
- [Hermes command secret source](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/command)
- [Hermes MCP configuration](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md)
- [Secure Browser MCP](https://github.com/tkhq/secure-browser-mcp)
