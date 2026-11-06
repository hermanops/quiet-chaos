---
name: release
description: "Prepare repository-aware SemVer releases with changelog updates, validation, and explicit approval gates for tagging and publication."
argument-hint: "Optional: target repository/component, version or bump, release scope, base tag, and release date"
agent: agent
---

# Release Preparation

Manage a software or infrastructure release in the current repository. Treat user
arguments as preferences, not approval to perform protected actions. Do not assume
a programming language, build system, hosting provider, or deployment target.
Follow applicable repository instructions and release conventions.

## Safety Boundaries

- Start with read-only inspection. Record the repository root, current branch,
  HEAD commit, remotes, and staged, unstaged, and untracked changes. Do not expose
  credentials embedded in remote URLs, configuration, logs, or command output.
- Preserve existing work. Never reset, clean, stash, switch branches, discard,
  stage, or commit changes without explicit approval for that action. Never
  overwrite user edits. If required edits overlap existing work, ask how to
  proceed before touching those files; unrelated changes can remain untouched.
- Never push, publish packages or images, deploy, execute infrastructure changes,
  or modify remote resources without explicit approval for the specific action,
  target, and version. Local preparation is not publication approval.
- Creating an annotated local Git tag and creating a GitHub Release each require
  explicit approval. A combined approval is valid only when both exact actions
  and targets were presented. A generic request to prepare a release is not consent.
- Never overwrite, force-update, delete, or reuse an existing tag or release.
  Do not bypass hooks, failed gates, branch protections, or signing requirements.
- Inspect commands, scripts, hooks, and CI triggers before running them. Tests,
  builds, tag pushes, and release creation can trigger publishing or deployment;
  require separate approval for those side effects, or stop before triggering them.
- Do not install tools, download dependencies/providers/modules, fetch Git refs,
  or access live environments without permission. Read-only remote metadata
  queries are allowed when access is available; report failures and stale evidence.

## 1. Discover the Release Contract

Inspect repository instructions, documentation, release workflows, manifests,
version files, changelog, and relevant CI configuration. Identify:

- The release unit: application, image, chart, module, role, collection,
  configuration bundle, or independently versioned monorepo component.
- Authoritative version sources, generated files, synchronization rules, tag
  prefixes, supported platforms, required checks, artifact expectations, signing,
  and existing release tooling. Reuse that tooling when safe.
- The latest applicable SemVer release tag, not simply the most recently created
  tag. Check reachability from the intended release commit, prerelease status,
  component scope, and existing GitHub Releases when available.
- The change range from the applicable release tag to HEAD, including merge
  history, diffs, migration notes, and unreleased changelog entries. Account for
  local changes separately; do not imply they are included in a committed release.

If tags or release history are missing, inaccessible, divergent, or ambiguous,
state the limitation and ask only questions needed to choose the release unit,
baseline, target commit, or initial version. Do not invent a previous version.

## 2. Recommend a Version

Use Semantic Versioning: MAJOR.MINOR.PATCH. Retain the repository's tag prefix
(for example, `v1.2.3` or a component prefix) separately from the version itself.
Use prerelease identifiers only when requested or required by repository policy.

- MAJOR: incompatible public API, configuration/schema, module interface,
  deployment contract, or supported upgrade-path changes.
- MINOR: backward-compatible functionality or optional capabilities.
- PATCH: backward-compatible fixes, security corrections, or maintenance.

Judge actual compatibility impact, not commit subjects alone. Dependency,
image, provider, role, chart, and configuration changes are not automatically
PATCH releases. Explain the affected consumer contract. For `0.x` versions,
follow documented compatibility policy; ask if breaking-change policy is unclear.
Do not silently promote to `1.0.0` or replace an explicit requested version.

Present the baseline tag/commit, proposed version/tag, release scope, and evidence
for the bump. If user preferences conflict with SemVer or repository policy,
resolve the conflict before edits. An unambiguous supported recommendation may
proceed to local preparation without approval for protected actions.

## 3. Prepare Local Release Changes

Update authoritative version files and their required derived metadata using
repository conventions. Preserve constraints and reproducibility. Do not change
unrelated dependency, provider, module, base-image, or tool versions. Never change
Terraform state, secrets, credentials, or live cluster/environment configuration.

Update `CHANGELOG.md`, creating it if absent unless repository policy specifies
another canonical changelog. If policy conflicts with this requirement, ask
before proceeding. Follow Keep a Changelog conventions:

- Keep `Unreleased` for changes not included in this release.
- Add `## [MAJOR.MINOR.PATCH] - YYYY-MM-DD`, using the actual agreed release date.
- Group entries under applicable `Added`, `Changed`, `Deprecated`, `Removed`,
  `Fixed`, and `Security` headings; omit empty categories.
- Describe user/operator impact, compatibility breaks, migration steps, and
  relevant issue/PR references. Verify claims against repository evidence.
- Preserve historical entries and existing comparison links. Add valid version
  comparison links when the hosting URL and tag convention are known.

Draft GitHub release notes from the same categorized entries, with explicit
breaking changes, upgrade/rollback considerations, and known limitations where
applicable. Do not claim unbuilt artifacts, unrun tests, or completed deployments.
Show the changed files and diff summary; avoid adding redundant release files.

## 4. Validate the Candidate

Discover commands from repository instructions and CI rather than assuming a
toolchain. Run the required safe local tests, lint, formatting checks, security
checks, builds, and configuration validation for the affected release unit.
Use installed tools and isolated/offline modes where supported. Examples are
conditional, not a universal checklist:

| Repository surface | Relevant checks |
| --- | --- |
| Applications/libraries | Declared tests, lint, type checks, builds, version consistency, packaging metadata |
| Docker | Dockerfile lint, build/context checks, approved local build and smoke checks; no registry push |
| Docker Compose | Compose model validation with repository environment inputs; no stack startup by default |
| Terraform | Formatting and validation with approved local initialization; no backend/state access or plan/apply/destroy by default |
| Ansible | Lint, syntax checks, role/collection validation, existing isolated tests; no live inventory execution |
| Kubernetes/Helm/Kustomize | Offline render, schema and policy validation; no cluster access or apply by default |
| Configuration repositories | Format/schema validation, reference integrity, policy and compatibility checks |

Avoid displaying resolved Compose secrets or rendered sensitive manifests.
Terraform plans and Ansible check mode can contact or affect real systems; do not
treat them as inherently safe. Ask before any such environment access.

Record each command, exit result, scope, and skipped/blocked check with its reason.
Revalidate changed inputs after fixes. Separate local evidence from CI results;
identify the commit each CI result validates. Never mark an unavailable check as
passed. Do not fix unrelated failures or expand scope without approval.

## 5. Report Release Readiness

Produce this concise report before requesting tagging or publication approval:

```text
Decision: GO | NO-GO
Candidate: <component/version, exact tag, branch, and full commit SHA>
Baseline: <previous applicable tag and commit, or explained initial release>
Scope: <included changes; excluded or uncommitted changes>
Version rationale: <compatibility impact and bump evidence>
Prepared files: <version/changelog changes and working-tree status>
Validation: <PASS/FAIL/BLOCKED/SKIPPED per required gate, with evidence>
Risks: <breaking changes, migrations, security, rollback, limitations>
Blockers: <required remediation or none>
Approval requested: <exact next protected actions and their side effects>
```

GO requires all mandatory gates to pass for the exact release candidate, version
consistency, and confirmation that the intended tag and release do not exist.
Use NO-GO for failed/blocked mandatory checks, unknown remote tag/release
availability, or intended release edits that are still uncommitted. Explain how
to reach GO; never silently waive checks. An unrelated dirty file is not grounds
to discard work: keep it out of the release and state the validated scope.

If preparation needs a commit, request approval for the exact file list first.
Stage only those paths after approval, verify the staged diff contains no other
work, and commit only with explicit permission. Recheck the candidate and checks
against the resulting commit before requesting tag/publication approval.

## 6. Tag and Publish Only After Approval

Stop and wait for approval naming the repository, exact version/tag, full commit
SHA, and requested actions. Show the proposed annotated tag message and final
release notes. Identify whether the GitHub Release will be draft, prerelease, or
published; include tag-push and automation side effects in the approval request.

After approval, recheck HEAD, candidate tree, validation evidence, local/remote
tags, and GitHub Releases for collisions. If scope or commit changed, invalidate
the previous approval and repeat readiness checks. If collision checks cannot be
completed, stop. Never use force flags or allow tooling to silently create a tag
at the default branch tip.

Create an annotated tag explicitly targeting the approved commit, using signing
when required. Push only that tag if separately authorized, never all tags or
unrelated commits. Verify the remote tag resolves to the approved commit before
creating a GitHub Release from that existing tag using the approved notes and
publication status. Do not let release tooling auto-push or auto-create tags.

If GitHub tooling/authentication is unavailable or the repository is not hosted
on GitHub, report the limitation and provide pending manual steps without
pretending a release exists. If publication fails partway through, report exact
local/remote state; do not delete, overwrite, or automatically roll back resources.

Finish with completed actions, commit/tag, release URL when actually created,
validation summary, and actions still awaiting approval. Package publication,
image publication, deployments, and infrastructure changes remain out of scope
unless separately and explicitly authorized.