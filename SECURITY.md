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
  wheel depends on the target machine's CUDA version.
- **Model, tokenizer and adapter revisions are not pinned** to commit SHAs. A compromised
  upstream Hugging Face repository could serve different weights.
- **The Colab notebook clones mutable `main`** rather than a tagged commit.
- **Commits are unsigned** and `main` requires no review. Single-maintainer repository.
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

Security posture last reviewed **2026-08-05**.
