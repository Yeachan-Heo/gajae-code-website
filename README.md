# Gajae Code Website

Static GitHub Pages website for [Gajae Code](https://github.com/Yeachan-Heo/gajae-code). The v0.10.0 release is a manual bootstrap that predates the expected/final npm-evidence protocol, so the site describes only release binary and npm availability and makes no evidence-verification claim for that seed. Automated advancement is fail-closed until a strictly newer complete release carries both expected and final evidence for its exact npm packages.

## Site architecture

The release path is website-owned and marker-scoped:

1. `sync-release.yml` resolves the latest complete, non-draft, non-prerelease source release from `Yeachan-Heo/gajae-code`.
2. The resolver verifies the immutable tag, peeled commit, matching source checkout, changelog, five binaries, and final evidence for exactly 14 public npm packages.
3. `sync-release.py` consumes only that verified snapshot and detached source sidecar. It has no network access and atomically renders the declared release markers plus `release-sync.json`.
4. The Writer App updates `automation/release-sync` through lease/CAS checks and opens or refreshes one PR. It never writes `main` directly.
5. Trusted default-branch validation and the Policy Reviewer App determine whether the exact generated-only Writer PR can receive the required approval. Pages observation compares the deployed `release-sync.json` and homepage `meta[name="gajae-release"]` with the committed release state.

Only marker-bounded release content is automation-owned. Human-owned shell, evergreen documentation, and historical release facts remain unchanged outside those regions. The inline docs-nav marker is the sole inline exception; all other release markers occupy their own lines.

## Repository contents

- `index.html` — landing page and the generated current-release badge/strip.
- `docs/` — static documentation, including generated latest-release navigation, card, and release notes regions.
- `css/styles.css` and `js/main.js` — shared presentation and behavior.
- `scripts/` — resolver, generator, ownership, transaction, and validation tools.
- `release-sync.json` — generated deployed-release state.
- `release-sync-control.json` — human-owned active/hold control and blocked release IDs.

## Release Apps and review contract

Production uses three separately registered, repository-scoped GitHub Apps. Credentials are never shared between Apps or with sandbox.

| App | Installation and permissions | Consumer and boundary |
| --- | --- | --- |
| **Gajae Website Release Sync Writer** | Website only; Metadata read, Contents read/write, Pull requests read/write. No Actions, Checks, Administration, Pages, or bypass. Environment: `release-sync-writer`; secrets: `GJ_RELEASE_SYNC_WRITER_APP_ID`, `GJ_RELEASE_SYNC_WRITER_PRIVATE_KEY`. | `sync-release.yml` only. Mints after tokenless CAS, writes the leased bot ref, creates/updates the PR, and enables exact-head auto-merge only after review and checks pass. |
| **Gajae Website Release Sync Trigger** | Website only; Metadata read, Actions read/write only. Source environment: `website-release-sync-trigger`; secrets: `GJ_RELEASE_SYNC_TRIGGER_APP_ID`, `GJ_RELEASE_SYNC_TRIGGER_PRIVATE_KEY`. | Source's warning-only latency hint dispatches `sync-release.yml` on website `main` with bounded inputs. It has no Contents or PR authority. Hourly/manual website reconciliation remains authoritative. |
| **Gajae Website Policy Reviewer** | Website only; Metadata read, Contents read, Pull requests read/write. No Contents write, Actions, Checks, Administration, Pages, merge, or bypass. Environment: `release-sync-policy-reviewer`; secrets: `GJ_WEBSITE_POLICY_REVIEWER_APP_ID`, `GJ_WEBSITE_POLICY_REVIEWER_PRIVATE_KEY`. | Trusted `review-release-sync-pr.yml` only. After trusted classification and head/base/control CAS, it may list, dismiss, or approve its own review. |

Repository variables freeze Writer and Reviewer App slug and numeric ID, plus `RELEASE_SYNC_AUTO_REVIEW_ENABLED`. Never use a PAT, shared App credential, `repository_dispatch`, direct source content write, or bypass as a substitute.

## Branch protection and CODEOWNERS

Protect `main` with ordinary native GitHub protection:

- Require a pull request and one current approval.
- Dismiss stale approvals, require approval of the latest reviewable push, require conversation resolution, and require branches to be up to date with strict validation/site checks.
- Require Code Owner review for policy paths, prohibit force pushes and deletion, and grant no App or actor bypass.
- Allow the Policy Reviewer App to approve only a non-draft, canonical-repository `automation/release-sync` PR made by the exact Writer App whose changed paths and marker ownership are exact. Human, fork, draft, tampered, and policy-changing PRs require a maintainer approval.

`.github/CODEOWNERS` protects workflows, scripts, release control, and this runbook for human review. Generated release HTML and schema-stable `release-sync.json` deliberately remain outside CODEOWNERS so an exact generated-only PR can satisfy the one native approval through the Policy Reviewer App.

If App identity, approval counting, dismissal, or lifecycle safety cannot be proven, set `RELEASE_SYNC_AUTO_REVIEW_ENABLED=false`, disable Writer auto-merge, and require a human maintainer approval. Do not weaken protection.

## Production and sandbox isolation

Production accepts only `Yeachan-Heo/gajae-code`, `Yeachan-Heo/gajae-code-website`, `https://registry.npmjs.org`, the production 14-package set, and `automation/release-sync`. Production workflows do not accept repository, registry, or environment overrides.

Sandbox is separate:

- Source: `Yeachan-Heo/gajae-code-release-sandbox`; target: `Yeachan-Heo/gajae-code-website-sync-sandbox`.
- Registry: `https://npm-release-sandbox.gajae.dev`, HTTPS with trusted TLS, authenticated reads/publishes, and seven-day retention.
- Sandbox Writer, Trigger, Reviewer Apps, credentials, schemas, validators, assets, package namespace, and run keys are separate from production.
- Health/auth checks and a disposable publish/read/delete probe must pass from both sandbox repositories before the complete cross-repository matrix. Per-process Verdaccio is valid only for hermetic local tests.

Missing sandbox infrastructure blocks production activation; it does not permit production npm use, a local registry substitute, shared credentials, or a sandbox override of production constants.

## Local preview and verification

No build step is required for a visual preview:

```bash
python3 -m http.server 8080
open http://localhost:8080
```

The self-contained website checks are:

```bash
python3 scripts/test-release-sync.py
python3 scripts/test-release-sync.py --case resolver-generator
python3 scripts/test-release-sync.py --case ownership-review-cas
python3 scripts/validate-site.py
python3 scripts/check-version-drift.py --self-test
python3 scripts/sync-release.py --self-test
python3 scripts/check-generated-ownership.py --self-test
python3 scripts/check-review-eligibility.py --self-test
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/*.yml
git diff --check
```

For a real verified snapshot, run `sync-release.py` with its snapshot and adjacent detached `source` sidecar; never point it at a mutable checkout or fetch network data from the generator.

## Hold, rollback, and recovery

`release-sync-control.json` is human-owned. It has a closed schema with `mode: active|hold`, a reason, and blocked integer release IDs; the bot never edits it.

To stop a bad release, merge a human-reviewed PR that sets `hold`, records the reason and bad release ID, and confirm schedule, manual dispatch, source hint, and every privileged CAS boundary stop before token mint. Then:

1. Disable exact-head bot auto-merge, close the PR, and conditionally delete only the observed bot ref.
2. Revert the sync commit and matching prior release state through a validated PR.
3. Observe the previous release live in Pages.
4. Publish a corrected, strictly newer source release. Never move or delete the old tag.
5. Merge a human resume PR that restores `active` while retaining blocked IDs; reconciliation may propose only a newer complete release.

## Phased cutover

1. Merge website bootstrap/manual verify-only code and disable the legacy `sync-version.yml` writer.
2. Merge source release-policy code in non-enabling/manual-sandbox mode.
3. Provision and health-check the persistent sandbox registry and separate sandbox App credentials.
4. Pass the full source → registry → target sandbox matrix.
5. Activate production immutable tag settings and stable-finalization-last source release flow.
6. Configure production protection, Apps, and manual Writer; run verify-only, manual reconciliation, and Pages/source observation.
7. Enable hourly Writer reconciliation, verify one no-op, then enable and test the warning-only Trigger hint last.
8. Delete the disabled legacy workflow through a focused human-reviewed cleanup PR only after observation succeeds.

## Focused delivery and fail-closed gates

Before remote gates, run the affected local/hermetic checks and a diff audit. Stage only task-owned paths; never use `git add .`, stash, reset, revert, rebase, or force push to work around a failure. Create focused commits, push the current feature branch without force, and make corrections as additional focused commits and non-force pushes.

Stop without writes or privilege escalation when release/tag/package evidence is incomplete or inconsistent; the source checkout, changelog, marker template, static links, state/control schema, ownership guard, lease/CAS tuple, App identity, required checks, native review lifecycle, or sandbox registry is invalid or unavailable. Safe degraded states are human-reviewed bot PRs, hourly/manual reconciliation without the trigger hint, and production remaining disabled pending infrastructure.