# Security Policy

## What this repository is

`edgar-extract` is a **local research pipeline**, not a hosted service. It runs as a CLI on
a workstation and as a notebook on Colab/Kaggle: it collects public SEC filings, builds a
dataset, trains a LoRA adapter and measures the result. There is no server, no multi-user
surface, no authentication and no user-data store. That makes the remote attack surface
narrow, and it should shape what counts as a realistic report.

The trust boundaries that do exist:

- the GitHub account and the mutable `main` branch
- repository code cloned and executed by the Colab/Kaggle notebook
- PyPI packages and their transitive dependencies
- Hugging Face model / tokenizer / adapter repositories
- HTTPS responses from SEC EFTS and Archives
- the tracked dataset of SEC cover-page excerpts

## Reporting a vulnerability

Please use **GitHub private vulnerability reporting** —
[Security → Report a vulnerability](../../security/advisories/new). That keeps the report
private until a fix ships. Please don't open a public issue for a security problem.

This is a personal research project maintained by one person: no bug bounty, no
response-time guarantee, best-effort reply.

Useful things to include: affected file and line, the preconditions an attacker needs, and
what the attacker gains. Reports that assume a compromised `sec.gov` response, or a
compromised PyPI / Hugging Face account, **are in scope** — some existing mitigations target
exactly that case — but please say so explicitly, because the precondition drives severity.

## Supported versions

Only the current `main` branch. There are no releases and no backports.

## Known and accepted limitations

Deliberate trade-offs, not oversights. Please don't file these as new findings:

- **No dependency lockfile.** `requirements-train.txt` pins five direct packages; the
  transitive tree is not pinned, and `torch` is intentionally excluded because the correct
  wheel depends on the target machine's CUDA version. `pip-audit` in CI narrows this — it
  resolves the five pins to 57 packages and audits all of them — but auditing a tree is not
  the same as freezing it: two runs a week apart can install different versions.
- **Model, tokenizer and adapter revisions are not pinned** to commit SHAs. A compromised
  upstream Hugging Face repository could serve different weights.
- **The Colab notebook clones mutable `main`** rather than a tagged commit.
- **Commits are unsigned** and `main` requires no review. Single-maintainer repository.
- **No required status check on `main`** — a deliberate decision, not an oversight. Deletion and
  force-push are blocked, because those lose work irreversibly. A required check would only stop a
  broken commit from sitting on `main` for a few minutes: CI runs on every push and fails within
  about a minute, `main` is not deployed anywhere, and this repository has never used a pull
  request (41 commits, one maintainer, zero forks). The accepted risk is a red commit on `main`
  until the next push.
- **The `audit` workflow may go red for something this repository cannot fix.** Its second
  `pip-audit` step covers `torch` and the packages the runner brought along, none of which are
  pinned here. A red there means "the installed stack has a published advisory", which is
  worth knowing even when the answer is to wait for an upstream release. It is a separate
  workflow from `tests` so that this kind of red never gets confused with a broken pipeline.
- **`torch` from the PyTorch CPU index cannot be audited under its installed name.** The wheel
  is stamped `2.13.0+cpu`, a local version identifier PyPI has no release for, so pip-audit
  skips it. The job strips the local segment before auditing. Worth stating plainly because
  the failure mode without `--strict` is silent: the largest dependency in the project would
  have been quietly excluded from a green audit.
- **CodeQL would not have caught `C-01`, and that is measured.** The same CLI and suite were
  run against this repository at `6e26931` — the commit before the input-validation fix, with
  the unvalidated SEC `_id` still reaching a filesystem path — and reported **0** findings,
  while the positive-control file above reported 2 from the same query. `py/path-injection`
  sources come from `ActiveThreatModelSource`, and `Requests.qll` models `requests` purely as
  an outgoing client call, so nothing read out of an HTTP response is treated as tainted.
  Static analysis narrows the blind spot here; it does not cover the trust boundary this
  repository actually depends on.
- **The runner ships a vulnerable `setuptools`.** Image 78.1.0 carries CVE-2025-47273 and
  CVE-2026-59890. Neither is reachable from anything here — no `easy_install`, no sdist build —
  and the `audit` job upgrades setuptools before installing rather than pinning the badge red
  on something only GitHub can bump. No `--ignore-vuln` is used anywhere; the gate still covers
  every package.
- **`.gitleaks.toml` carries one allowlist entry**, for a documentation line that the
  `generic-api-key` rule matches because the word *accession* contains *access*. It is keyed
  to the matched text rather than to a `file:line` fingerprint, so it cannot drift onto a
  different line and silence a real finding. It was verified not to suppress planted
  credentials in the same file.
- **The tracked dataset redistributes excerpts of public SEC filings.** These are corporate
  securities documents; no personal data was found in them. Redistribution terms of the
  underlying filings are a separate, non-security question.

## Hardening already in place

- `src/edgar.py` validates accession / CIK / document-name **format** on values taken from
  the SEC full-text-search response before they reach a URL or a filesystem path.
- HTTP redirects are followed manually and the target host is checked **before** each
  request, so the self-identifying `SEC_EDGAR_UA` header (which SEC requires to carry a
  contact address) cannot be carried to a non-`sec.gov` host.
- Secrets live only in `.env` / environment variables, which are git-ignored.
- GitHub secret scanning and push protection are enabled.
- CI pins every GitHub Action to a full commit SHA and runs with `contents: read`.
- **CodeQL** (`security-extended`) analyses the Python on every push and weekly. Measured on
  `2c8b675`: 50 rules, **0 results**, over all 25 Python files in the repository — the run log
  names each one as `Extracted file`, so the empty result is not an empty database. The empty
  result was also positive-controlled off-CI: the same CLI (2.26.3) and suite, run against a
  file where a Flask `request.args` value reaches `open()`, reports 2 `py/path-injection`
  findings. See the `C-01` note under limitations for what the same run says about this
  repository's own history.
- **pip-audit** runs twice per CI run: once over `requirements-train.txt` resolved to its
  transitive tree (**57 packages**), once over the environment that was actually installed
  (**76 packages**). Both use `--strict`, so a package that could not be audited fails the job
  instead of disappearing into a "no known vulnerabilities found" line. That guard has already
  paid for itself — see the `+cpu` note below.
- **gitleaks** scans the entire commit history (`--log-opts=--all`, non-shallow checkout) on
  every push and weekly, and uploads SARIF to the Security tab. It runs `--redact`: this
  repository is public and so are its Actions logs, so an unredacted finding would publish the
  secret the job exists to catch. Verified against planted credentials: the redacted SARIF
  contains none of the three fabricated values, only `REDACTED`.
- `tests/test_workflows.py` guards the controls above against silent decay — an action
  re-pinned to a movable tag, a dropped checksum verification, a dropped `--redact`, a
  shallow checkout, a removed schedule. Each of those eleven mutations was applied and
  measured to turn the suite red (2026-08-19).

Security posture last reviewed **2026-08-19**.
