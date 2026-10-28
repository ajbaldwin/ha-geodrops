# Releasing

This repository is distributed via a HACS **custom repository**, with
`hacs.json`'s `hide_default_branch: true`. That setting means HACS only ever
offers users **tagged releases** — never the tip of `main` — so a change
isn't available to installs until it's tagged and released. There is no
separate "publish to HACS store" step: publishing a GitHub release *is* the
publish step.

## Beta and stable

Releases go out on two channels, both as GitHub releases:

- **Beta — `X.Y.Z-beta.N`**, published as a GitHub *pre-release*. HACS offers
  it only to users who turned on this integration's **Pre-release** switch —
  since HACS 2.0 a per-repository switch entity, disabled by default (see the
  README's *Beta versions*). You run it on your own box first.
- **Stable — `X.Y.Z`**, the release every HACS user is offered.

**By default, merged changes ship as a beta.** Fixes found while a beta is out
go into the next beta (`-beta.2`, `-beta.3`, ...), not into a string of stable
patches. Promote to stable when you judge the beta ready. Nothing enforces the
wait, so the discipline is yours. A direct stable (no beta) is still allowed
for an urgent fix to a bug in the current stable.

Version numbers: betas carry the version the stable will get — the first beta
after 0.5.1 is `0.6.0-beta.1` (or `0.5.2-beta.1` for fixes only), and
promoting it is `0.6.0`. Never publish a beta of a version that is already
stable; it would sort below it (`tools/release.sh` refuses).

**Never go past `-beta.9`.** HACS doesn't sort releases by version: it offers
the first non-draft pre-release in GitHub's releases list, and that list isn't
reliably in version order: it has listed a `-beta.9` ahead of the `-beta.10`
published after it, so HACS never offered that `-beta.10`. After `-beta.9`,
promote the stable or move to the next patch's betas (`X.Y.(Z+1)-beta.1`).
`tools/release.sh` refuses `-beta.10` and up, and after publishing it checks
that GitHub lists the new release first.

CHANGELOG sections:

- **Each beta** gets its own section, `## 0.6.0-beta.2 — Title`, covering what
  changed since the previous beta. Beta users read it as that release's notes.
- **The stable** gets `## 0.6.0 — Title` summarizing *everything* since the
  previous stable, written for users who skipped every beta. Don't just point
  at the beta sections. The beta sections stay in the file.

## Steps

1. **Put the release changes in the PR that ships.** There is no separate
   release PR for a beta: the feature or fix PR you mean to release carries
   two extra changes. (A stable promotion has no code to ride along with, so it
   gets a small `release: vX.Y.Z` PR with just these two changes, or you fold
   them into the next feature PR.)

   - **Bump the version** in `custom_components/geodrops/manifest.json`: the
     next beta (`0.6.0-beta.1`, ...) or the stable (`0.6.0`), no leading `v`.
     The tag will be `v` + this version.
   - **Write the release notes** as a new top section in `CHANGELOG.md`,
     headed `## X.Y.Z — Title`. `tools/release.sh` publishes that section
     verbatim as the GitHub release body, and HACS renders the body as the
     changelog shown to users before they update. Write a short,
     human-readable summary of what changed and why it matters to someone
     deciding whether to update — never a raw commit log. Keep it brief:
     one sentence per change, no implementation details (library versions,
     how a value is computed), and a single closing line on entity counts
     or anything users must do.

   Only one open PR should carry a bump at a time, because two would conflict
   on the version line and the top of `CHANGELOG.md`. If a second PR needs to
   ship too, merge the first, rebase the second, and bump to the next beta.

2. **Merge it**, then publish from an up-to-date `main`:

   ```bash
   git checkout main && git pull
   bash tools/release.sh publish --dry-run
   bash tools/release.sh publish
   ```

   The script refuses unless you are on a clean `main` that matches
   `origin/main`, the CI and Validate workflows (and any other push-triggered
   workflow) passed on that commit, the tag is new, a beta's number is 9 or
   less, and `CHANGELOG.md` has the version's section. Only push runs count, so
   a failed **Publish release** dry run doesn't block. It waits up to 15 minutes
   (`RELEASE_CI_TIMEOUT`) for CI runs that haven't started or finished yet, so
   you can publish right after the merge. It then tags `vX.Y.Z` and creates the GitHub
   release — a pre-release for `-beta.N`, the latest release for a stable —
   titled with the CHANGELOG heading's subtitle (HACS already shows the tag
   in front of it), or with the tag when the heading has none. Last, it checks
   that GitHub lists the new release first among releases of its kind, since
   that is the one HACS offers. `--dry-run` runs every check and shows the
   notes without publishing.

   **Or publish from GitHub** (no local `gh` needed): Actions → **Publish
   release** → Run workflow on `main`. It runs the same `tools/release.sh`;
   `dry_run` is on by default, so run it once as a dry run, check the log, then
   run it again with `dry_run` off. A release created this way doesn't trigger
   the release guard below (GitHub doesn't start workflows from a workflow's
   own token), so the job runs `tools/check_release.sh` itself and fails if the
   release is inconsistent.

3. **Verify in HACS.** After the release publishes, HACS should offer the new
   version as an update (a beta only with the Pre-release switch on) within
   its normal refresh window.

**Release guard.** `.github/workflows/release-guard.yml` re-checks every
published or edited release — including ones made by hand in the GitHub UI —
with `tools/check_release.sh`: the tag must equal `v` + the manifest version at
that tag, and the pre-release flag must match the version. On a mismatch it
turns the release back into a draft (HACS stops offering it) and the run
fails. Fix the cause, then publish the draft again.

## Notes

- Version numbers are semver (`MAJOR.MINOR.PATCH`). Bump `PATCH` for
  fixes, `MINOR` for backwards-compatible features (e.g. a new sensor),
  `MAJOR` for anything that breaks existing config entries or entity IDs.
- The manifest `version` and the git tag must agree, or HACS will show a
  confusing version mismatch to users comparing the release notes to what
  they see installed. `tools/release.sh` and the release guard both enforce
  this.
