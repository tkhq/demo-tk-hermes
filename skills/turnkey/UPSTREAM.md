# Upstream: tkhq/turnkey-agent-skills

Vendored from https://github.com/tkhq/turnkey-agent-skills at commit
`ce43ab6b04fbbeaa92389abb7622e1bd715e0b7f` (branch `zeke/agent-identity-skills`,
PR #26, which stacks on PR #23 and PR #25).

| Here | Upstream |
| --- | --- |
| `tk-cli/SKILL.md` | `SKILL.md` (root index) |
| `tk-cli/references/cli-coverage.md` | `references/cli-coverage.md` |
| `tk-cli/references/agent-policy-patterns.md` | `references/agent-policy-patterns.md` |
| `managing-secrets/`, `managing-policies/`, `monitoring-activities/`, `provisioning-agent-identity/` | `skills/<name>/` without their `evals/` directories |

Two edits were made so the files work inside a Hermes skills category:

- Links to the upstream root (`../../SKILL.md`, `../../references/...`, one level deeper from
  `references/` files) point at `tk-cli/...`. Links to skills that are not vendored here
  (managing-users, provisioning-agent, and so on) are plain text.
- In `tk-cli/SKILL.md`, the skills table links only to the four vendored skills; the other
  rows are plain text. `scripts/check-cli.sh` is mentioned but not vendored; run it from a
  turnkey-agent-skills checkout.

These skills require the tk CLI at 0.2.0 or later. `secret env`, `policy create --name`, and
`user create --user-name` come from https://github.com/tkhq/tk/pull/44 until it merges.

To refresh: check out the new commit, repeat the copy above, re-apply the two edits, and
update the commit here.
