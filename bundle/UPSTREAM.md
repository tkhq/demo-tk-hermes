# Upstream: tkhq/secure-browser-mcp

`bundle/secure-browser-mcp/` is an unmodified snapshot of tracked files from
https://github.com/tkhq/secure-browser-mcp at commit
`21ff1afc926f7f5ae8f764458cb899f38a52cfe6` (branch `carey/hermes-onboarding`, PR #8).
Once PR #8 merges, re-pin to the resulting `main` commit; the content is the same.

Included: `src/`, `test/` (with fixtures), `skills/`, `docs/`, `vendor/` (upstream's vendored
Turnkey SDK tarballs), `package.json`, `bun.lock`, `tsconfig.json`, `README.md`, and
`scripts/import-secret.ts` because `test/onboarding.test.ts` imports it. The profile documents
secret import through the tk CLI instead; the script is here for the tests.
Excluded: the rest of `scripts/`, `evals/`, `assets/`, `dist/`, `.env*`, `node_modules/`, credentials,
screenshots, and eval outputs.

Copy command, run from a clean checkout of the pinned commit:

```sh
git rm -r -q bundle/secure-browser-mcp && mkdir -p bundle/secure-browser-mcp
(cd "$UPSTREAM" && git ls-files -z src test skills docs package.json bun.lock tsconfig.json README.md vendor scripts/import-secret.ts \
  | tar --null -T - -cf -) | tar -C bundle/secure-browser-mcp -xf -
cp -R bundle/secure-browser-mcp/skills/secure-browser skills/
```

The bundled `package.json` still lists `skill:install`, `eval`, and `hermes:config`; those
reference `scripts/` and `evals/`, which are not vendored. This profile ships the skill itself
under `skills/secure-browser/` and generates the Hermes config with `scripts/profile.py`.

What changed since the previous pin (`fbb015f`): `list_secret_refs` reports `backend`;
pending fills return `approval_url`; the skill documents backend selection, supported fields,
and the approval link; `list_network_requests` is documented as an unavailable stub.

No license is asserted here beyond upstream's.
