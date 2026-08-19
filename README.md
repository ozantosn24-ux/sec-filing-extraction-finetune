# edgar-extract

[![tests](https://github.com/ozantosn24-ux/sec-filing-extraction-finetune/actions/workflows/tests.yml/badge.svg)](https://github.com/ozantosn24-ux/sec-filing-extraction-finetune/actions/workflows/tests.yml)
[![codeql](https://github.com/ozantosn24-ux/sec-filing-extraction-finetune/actions/workflows/codeql.yml/badge.svg)](https://github.com/ozantosn24-ux/sec-filing-extraction-finetune/actions/workflows/codeql.yml)
[![audit](https://github.com/ozantosn24-ux/sec-filing-extraction-finetune/actions/workflows/audit.yml/badge.svg)](https://github.com/ozantosn24-ux/sec-filing-extraction-finetune/actions/workflows/audit.yml)

Structured field extraction from SEC 424B5 preferred-stock prospectuses, built to
measure one question: **on schema-strict extraction, is a small fine-tuned model worth
more than the alternatives — on accuracy, abstention, latency and format adherence?**

Answer, on a company-disjoint held-out set: **yes against all three alternatives it was
measured against.** 61.1% whole-record versus 27.8% for a hand-tuned rule-based extractor,
0.0% for the same base model without the adapter, and 0.0% for a **twice-as-large prompted
model** (Qwen2.5-3B). The frontier-model comparison was *not* run (see
[Known limitations](#known-limitations)), so this is not evidence about GPT/Claude-class
models.

The task is not invented for a demo. A rule-based parser I wrote earlier
(`prefedge/backend/utils/edgar_parser.py`) gives up on exactly these fields:

> `Coupon/par/issue_size require fetching the full prospectus — left as None for now.`

Those values sit in dense legal prose on the cover page. Keyword matching does not
recover them reliably. This repository builds the dataset and the measurement.

## Status

| stage | state |
|---|---|
| 1. Dataset | **done** — 160 labelled records, 148 clean / 12 flagged; split train 99 / dev 25 / test 36 |
| 2. LoRA fine-tune (PyTorch) | **done** — Qwen2.5-1.5B, LoRA r=16, 3 epochs on a free T4 |
| 3. Evaluation | **done** — four contestants measured on test, once |
| 4. Epoch search | **done** — 5 epochs tested on `dev`, did not improve; 3 stands, test untouched |

**145 tests** run on every push (measured 2026-08-19; re-measure with `pytest -q`). CI rebuilds
the derived dataset first — `data/processed/` is git-ignored, and without that step **13 tests
skip** (measured without derived data: 132 passed / 13 skipped) while the badge stays green anyway.
So a skipped test fails the build: a suite that quietly stopped measuring is worse than a red one.

Three more checks run beside the suite, added 2026-08-19 to close the last open finding of the
[security review](SECURITY.md): **CodeQL** (`security-extended`), **pip-audit** on both the
declared stack and the environment CI actually installs, and **gitleaks** over the whole
history. What the badges do *not* tell you is in [Known limitations](#known-limitations).

## Result

Test set, 36 held-out records, 22 companies with zero overlap with training. Measured once,
after the checkpoint was chosen on `dev`. Every contestant gets the **same instruction**
(`src/prompt.py` is a single module for exactly this reason) and the same harness.

| metric | rule-based regex | base 1.5B, no adapter | prompted 3B (4-bit) | **fine-tuned LoRA 1.5B** |
|---|---|---|---|---|
| schema validity | 100.0% | 0.0% | 25.0% | **100.0%** |
| whole record exact (13/13) | 27.8% | 0.0% | 0.0% | **61.1%** |
| correct abstention | 90.2% | 61.0% | 59.3% | **92.7%** |
| **hallucination** (gold null → value emitted) | 9.8% | 39.0% | 40.7% | **7.3%** |
| miss (gold filled → null emitted) | 4.1% | 31.9% | 15.7% | **3.5%** |
| `par_value` ↔ `liquidation_preference` slice | 81.6% | 39.5% | 73.7% | **100.0%** (38/38) |
| single-instance `unit` generalization | hit | miss | miss | hit |
| median latency | 0.001 s | 6.81 s | 10.83 s | 8.93 s |

**A model twice the size, prompted, scores 0.0% whole-record.** Qwen2.5-3B in 4-bit is
better than the 1.5B base at reading the document — 73.7% on the hard slice versus 39.5% —
but it cannot hold the output contract: it **omitted a required field in 27 of 36 records**
(usually `is_preliminary`), put free text in enum fields twice, fenced one answer in
markdown, and emitted `"shares_offered": 20340632356.64` where an integer was required.
Schema validity 25.0%. It also hallucinates the most of any contestant (40.7%).

**The fine-tune beats the rule-based baseline 61.1% vs 27.8% on whole-record extraction,
and it does so without trading accuracy for recklessness** — hallucination went *down*
(7.3% vs 9.8%) and misses went *down* (3.5% vs 4.1%). On the hard case the project exists
for, `par_value` ↔ `liquidation_preference`, it is 38/38.

**The two prompted columns are what make that claim safe**, and they close two different
escape hatches:

- *"The base model already knew this."* The no-adapter run is the same weights, same
  instruction, same greedy decoding — only the adapter removed. It scores **0.0% schema
  validity**: it wrapped all 36 outputs in a markdown fence (an explicit instruction
  violation), emitted `is_preliminary: null` 10 times where the schema forbids null, put
  free text in enum fields, and produced one output that is not parseable JSON at all
  (`"shares_offered": 2,774,108`). The adapter is doing the work.
- *"It just needs a bigger model."* Qwen2.5-3B, twice the parameters, also scores **0.0%**
  whole-record. Scale helped it *read* (73.7% on the hard slice vs 39.5%) but not *comply*.

Neither contrast existed before the run; both are the reason the headline number means
anything.

The rule-based contestant is not a strawman: it is 100% schema-valid *by construction* and
81.6% on the hard slice. It loses on whole-record because keyword matching cannot resolve
which of two dollar figures in the same sentence is the liquidation preference.

**Latency is the honest cost.** The regex extractor is ~7,500× faster and runs on a CPU.
The fine-tune buys accuracy with a GPU and ~9 s/document. Which is worth more depends on
whether being wrong on 72% of records is acceptable. The 3B is both slower *and*
unusable here, which is the cleanest argument in the table: size alone bought nothing.

### How the checkpoint was chosen

Selection ran on `dev` (25 records), never on test:

| checkpoint | dev whole record | dev `eval_loss` |
|---|---|---|
| 13 (epoch 1) | 48.0% | 0.01938 |
| 26 (epoch 2) | 60.0% | 0.01551 |
| **39 (epoch 3)** | **68.0%** | **0.01169** |

Both signals agree, so there was nothing to adjudicate. Both were still improving at epoch 3,
which raised the obvious question: would more epochs do better?

**That thread is now closed — it was tested, and the answer is no.** A 5-epoch run (same
data, same seed, same hyperparameters, single T4) scores on `dev`: 52.0% → 56.0% → **76.0%**
→ 68.0% → 68.0%. **Epochs 4 and 5 make it worse.** The decision rule was written and
committed *before* the run (`schema/EPOCH_KARARI.md`) and the outcome is recorded there in
full, including why the config was **not** changed despite the rule technically passing: the
best checkpoint is still an epoch-3 checkpoint, and the `eval_loss` margin (0.00018) is
smaller than this project's own measured run-to-run noise (0.00022). **The test set was not
touched** for this experiment. Hyperparameter search proper — learning rate, rank — remains
undone.

### Baseline detail (rule-based)

Rules were developed against **train only** and run against test once. Train scores 33.3%
whole-record versus 27.8% on test; that gap is the cost of having tuned on train and is
reported rather than hidden. (The dev slice, also seen during rule development, scores
68.0% — a reminder that a 25-record slice is a noisy ruler and that absolute numbers
across splits are not comparable.)

### Training run, measured

| | |
|---|---|
| model | Qwen2.5-1.5B-Instruct, LoRA r=16 (q,k,v,o,gate,up,down) |
| hardware | free Colab **Tesla T4** — Turing, so **fp16**, chosen by the script from compute capability |
| precision | `Tesla T4 CC 7.5 (Turing) — bf16 YOK, fp16'ya dusuldu` |
| peak VRAM | **4.82 GB / 14.6 GB (33%)** with gradient checkpointing |
| optimizer steps | **39** (99 examples / effective batch 8 × 3 epochs) |
| wall clock | 19 min (`train_runtime` 1147 s) |
| train loss | 0.277 → 0.0364, no `nan` — fp16 held |
| cost | **$0** |

The run was executed twice (the first session died before the artifacts were saved). Dev
`eval_loss` reproduced to three decimal places across both runs — 0.01919/0.01552/0.01147
then 0.01938/0.01551/0.01169 — which is fp16 nondeterminism, not drift.

## Dataset

| split | documents | companies | preliminary (abstention) | par↔liq hard case |
|---|---|---|---|---|
| train | 99 | 47 | 37 | 56 |
| dev | 25 | 15 | 10 | 21 |
| test | 36 | 22 | 12 | 19 |

**`dev` is carved out of train, company-wise, and exists so that model selection has
somewhere to happen that is not the test set.** Epoch count, learning rate and which
checkpoint to keep are all chosen by looking at something; if that something is the
test set, then "it beat the rule-based baseline" means "it was tuned on the test set".
The repo already refuses that for the rule-based contestant — rules were developed on
train and test was run once. The fine-tune gets held to the same standard.

⚠️ **Dev is not a comparison surface.** The rule-based rules were tuned on all 124
train records back when dev was still part of train, so regex has seen dev: it scores
**68.0%** whole-record there versus **27.8%** on test. Dev is clean for the *model*
(which trains on 99 records and never sees it) and is used only to compare fine-tuned
checkpoints against each other. All four contestants meet on **test**, once.

**Company-wise split, zero company overlap.** Some issuers file repeatedly — Southern
California Edison appeared 10 times, State Street 9. A random document-level split would
put the same issuer's boilerplate on both sides and inflate the score.

**Abstention slice (59 records).** Preliminary prospectuses are filed before pricing, so
the coupon is literally blank: `a share of our % Fixed Rate Reset ... Preferred Stock`.
The correct label is `null`. A model only learns "say nothing when the text says nothing"
if the data contains cases where nothing is the answer.

## What the measurements changed

Every design decision below started as a reasonable assumption and was overturned by
looking at real documents. They are listed because the reasoning is the point.

**A fixed cover-page window is wrong.** An initial probe over 8 documents found every key
term within the first 3,368 characters — even in a 395,318-character filing. On a wider
sample, **58% of documents** put the title past character 6,000, pushed down by long
tables of contents. Replaced with anchor location.

**The anchor over-triggers without bounds.** Deep matches were checked and turned out to be
noise: UMH at offset 50,711 was `1.50% to 2.20% (depending on our overall leverage ratio)`
— a credit facility rate, not a coupon. Fixed by bounding the search window and validating
the coupon into a plausible range.

**Unit mismatch was the expensive one.** In the first labelling pass, **24 of 27** depositary
records paired the depositary share count with the underlying preferred's liquidation
preference: `12,000,000 × $25,000 = $300 billion`. The actual raise was $300 million.
Both quantities must refer to the same unit; `shares × liquidation_preference` is now a
consistency check. The distribution before and after the fix (first labelling pass) says it
plainly:

| liquidation preference | before fix | after fix |
|---|---|---|
| $25 (retail, NYSE-traded) | 16 | **49** |
| $50 (mandatory convertibles) | – | 7 |
| $1,000 (institutional) | 25 | 10 |
| $25,000 / $10,000 / $100,000 | 24 | **0** |

**Unicode whitespace silently breaks rule-based matching.** SEC documents are full of
U+2003, U+2007, U+2009 (964 occurrences across the corpus). A search for `par value`
returned zero matches on a document that says `par value $0.01 per share`. Left in place,
this would have crippled the rule-based baseline and handed the fine-tuned model an unearned
win — the comparison itself would have been dishonest.

**`series` does not identify a security.** Strategy Inc has four preferreds all designated
"Series A", distinguished by name: Perpetual Strike (8%), Perpetual Strife (10%, cumulative),
Perpetual Stride (10%, non-cumulative). What looked like contradictory labels was a real
distinction. Documented as a known limitation.

## The hard case

`par_value` and `liquidation_preference` appear in the same sentence and mean different
things:

> `6.625% Monthly Income Class F Cumulative Redeemable Preferred Stock, **par value $0.01
> per share**` … and in the fee table, `Proposed Maximum Offering Price Per Security:
> **$25.00**`

`$0.01` is the legal nominal value. `$25.00` is what matters for yield — coupon × 25 is the
annual dividend; coupon × 0.01 is meaningless. Worse, some filings never use the phrase
"Liquidation Preference" at all, so the value has to be inferred rather than matched.

This is the slice the fine-tuned model has to win on to be worth anything, and it is
reported separately in the evaluation.

## Reproduce

**The dataset ships with the repository.** `data/interim/labels/` (160 gold records) and
`data/interim/spans/` (the cover-page window each record was labelled from) are tracked, so a
clone can rebuild the training set, retrain and re-measure **without contacting EDGAR at all**:

```bash
pytest -q                            # 132 pass, 13 skip on a fresh clone; no data fetch needed
python src/build_sft.py              # labels + spans -> data/processed/sft_{train,dev,test}.jsonl
python src/extract_rules.py --split test
python src/evaluate.py data/processed/preds_regex_test.jsonl
```

The labels are tracked because they are the one artefact **the code cannot regenerate** — they
were produced by hand. Everything downstream of them is derived and stays gitignored.

The full collection pipeline, if you want to rebuild the corpus from scratch:

```bash
export SEC_EDGAR_UA="Your Name your@email.com"   # SEC requires a self-identifying UA
python src/collect.py --per-query 10 --max-docs 250   # fetch + locate spans
python src/split.py                                   # company-wise, deterministic
#   ... labelling step: spans -> data/interim/labels/<split>/<accession>.json
#   (already done — this is what the tracked labels are)
python src/normalize_labels.py                        # fix the label key set (see below)
python src/clean_dataset.py                           # applies data/exclusions.json, sweeps orphan spans
python src/validate_labels.py                         # consistency checks
python src/build_sft.py                               # -> data/processed/sft_{train,dev,test}.jsonl
python src/measure_tokens.py                          # seq_len decision, measured not guessed
python src/extract_rules.py --split test              # rule-based contestant
python src/evaluate.py data/processed/preds_regex_test.jsonl
pytest -q

# fine-tune (GPU) — see requirements-train.txt for pinned versions
python src/train_lora.py --smoke                      # CPU: proves the pipeline first
python src/train_lora.py --probe                      # GPU: peak VRAM on the LONGEST sequences
python src/train_lora.py                              # real run

# pick the checkpoint on dev — NOT on test
python src/predict.py --adapter models/lora-qwen2.5-1.5b/checkpoint-N --split dev \
  -o data/processed/preds_ft_dev_N.jsonl
python src/evaluate.py data/processed/preds_ft_dev_*.jsonl --split dev

# then test, once, with the chosen checkpoint
python src/predict.py --adapter models/lora-qwen2.5-1.5b/checkpoint-39   # dev picked epoch 3
python src/predict.py -o data/processed/preds_base1p5b_test.jsonl   # same model, no adapter
python src/predict.py --model Qwen/Qwen2.5-3B-Instruct --4bit \n  -o data/processed/preds_prompted3b_test.jsonl                     # twice the size, prompted
python src/evaluate.py data/processed/preds_regex_test.jsonl \
  data/processed/preds_base1p5b_test.jsonl data/processed/preds_prompted3b_test.jsonl \n  data/processed/preds_ft_test.jsonl
```

The no-adapter run is not optional. A fine-tuned score on its own cannot separate
"the LoRA taught it this" from "the base model already knew this" — the adapter has to
be measured against the same weights without it.

Order matters. `normalize_labels.py`, `clean_dataset.py` and `validate_labels.py` operate on
**labels**, so they run after labelling, not before. `split.py` only needs the collected
documents. Normalisation runs *before* cleaning: cleaning drops records with too few filled
fields, and a record missing the `offered_unit` key would be counted one field short.

`normalize_labels.py` exists because 42 of the wave-1 labels had no `offered_unit` key at all
(absent, not null) and 44 had no `depositary_ratio`. A target JSON whose key set varies from
record to record teaches an inconsistent output shape and makes "schema validity" undefined
as a metric. The script derives the missing values from the text and **refuses to guess**:
where the evidence does not decide, it stops and reports rather than filling something in.

`data/exclusions.json` is tracked and lists 12 accessions that `collect.py` retrieves but
which are not preferred-stock offerings (base prospectuses, common-stock ATM programmes,
resale registrations, one senior-notes offering), each with a reason. `data/company_keys_extra.json`
is tracked for the same reason: three wave-2 accessions were labelled without being written to
`manifest.json`, and the collection log they could be recovered from (`documents.jsonl`) is not
versioned, so without that file the company-wise split cannot be verified at all. Without both,
the pipeline is not reproducible — a fresh collection run would produce 172 documents where 160
belong in the dataset.

## The training script, and what the library docs actually say

`src/train_lora.py` was written against the TRL and PEFT documentation as of 2026-07-31
(TRL 1.9.2, transformers 5.14.1), not from memory. Three things would have been wrong if
written from recall, and two of them fail *silently*:

- The field is **`max_length`, not `max_seq_length`** — the old name is simply ignored — and
  its default is **1024**. A script using the old name trains on truncated data and reports
  nothing unusual.
- **`bf16` defaults to `True`** when `fp16` is unset. On Turing (T4 included) there is no
  bf16. So the copy-paste script dies exactly where G13 predicted. The script now picks
  precision from the card's compute capability, and refuses an explicit `--precision bf16`
  on Turing rather than silently downgrading it.
- When the model is passed as a string, **dtype defaults to float32** — 1.5B parameters in
  fp32 is ~6 GB of weights before a single activation.

Versions are pinned in `requirements-train.txt` for exactly this reason.

### Running it locally is blocked, on purpose

`torch` here is a CPU-only build and the machine has 16 GB. A 1.5B model is ~6 GB of fp32
weights before a single activation, and the measured CPU rate is **32 s/step for a 135M
model** — an order of magnitude larger puts the real run in the day range while the machine
swaps and becomes unusable. So `train_lora.py` checks the parameter count (read from the
Hub's safetensors metadata, no weights downloaded) and **refuses to train anything over
0.5B without CUDA** unless `--force-cpu` is passed. It names the free alternative rather
than just failing: see `COLAB.md`.

### The CPU smoke test earns its keep

```
python src/train_lora.py --smoke     # 135M model, 2 steps, no GPU
```

It runs the real pipeline end to end and prints the one number that matters before renting
anything: **loss is computed on 108 of 2,294 tokens (4.7%)**. That is the JSON target and
nothing else — confirming `completion_only_loss` masks the 700-token instruction. Without
that check, training would run happily while learning to reproduce the prompt, and the
failure would only surface after the GPU bill.

## Sequence length is measured, not assumed

`seq_len=2048` is the value most LoRA guides use. Measured with the Qwen2.5 tokenizer over
the actual chat-templated sequences, it **truncates every training record (99/99), 24 of 25
dev records and all 36 test records**. What gets cut is the end of the cover page — where the
fields are. A truncated example looks like a model failure in the metrics; it never saw the
text. Re-run `python src/measure_tokens.py` to reproduce these counts.

| | |
|---|---|
| longest full sequence | 2,626 tokens |
| `seq_len` with zero truncation | **3072** |
| the instruction itself | 700 tokens, repeated in every example — 32% of all training tokens |
| training set total | 217,169 tokens |

## Tests

```
pytest -q     # 145 tests with data/processed/ present; 132 pass + 13 skip on a fresh clone
```

Fixtures under `tests/fixtures/` are **real excerpts from real filings**, each carrying its
accession number and source URL. No invented examples: every bug this project found came
from real documents, not from imagined ones. The tests were mutation-checked — reverting
the whitespace normaliser, the coupon range validation or the search bound each turns a
test red.

The mutation audit is not decorative: it deleted code. An ADR/ADS pre-strip in
`normalize_labels.py` survived every mutation, which exposed it as unreachable on real data —
and on inspection it was harmful, since an American Depositary Share genuinely *is* a
depositary-like unit and should stop the deriver rather than be scrubbed out of the text.
The pre-strip was removed and replaced with a test pinning the conservative behaviour.

The audit also drove three fixtures into existence. Mutations that survived showed the tests
were passing for the wrong reason: a hand-written "without par value" sentence did not
actually exercise the no-par rule, because no competing `par value $0.01` appeared nearby.
The real Albemarle filing carries both, 894 characters apart. Same for the coupon range
(FAT Brands' "55.5% of the combined voting power of our Class A Common Stock" is anchored to
a security word but is not a coupon) and for depositary priority (Merchants Bancorp's
"$1,000 per share (equivalent to $25 per depositary share)", where a *different* series'
"liquidation preference $1,000" sits in the same window as bait).

## Known limitations

- **The prompted contestant is 3B, not a frontier model.** Qwen2.5-7B was the original
  plan and it killed the Colab session: `--4bit` quantises at *load*, but the fp16 weights
  still have to be **downloaded first — 15.2 GB**, which exhausted the free-tier session at
  32% and took `/content` (adapter and all predictions) with it. 3B (~6 GB) fits and was
  measured. So the honest claim is **"a small fine-tuned model beats a twice-as-large
  prompted open model"** — not "beats GPT/Claude". A frontier model with the same
  instruction would very likely produce valid JSON; that was never tested here.
- The 3B contestant got **one prompt, greedy decoding, no retries and no repair pass**.
  A production prompted pipeline would add JSON-mode/constrained decoding and a re-ask
  loop, which would fix most of its 27 missing-field failures. What is measured is
  "same instruction, same harness, no scaffolding" — not the ceiling of prompting.
- 36 test records is a small ruler. 61.1% vs 27.8% is a 12-record gap; the direction is
  not in doubt but the second decimal is meaningless.
- Epoch count **was** searched on `dev` and 3 stands: a 5-epoch run peaks at epoch 3 (76.0%)
  and degrades after (68.0%, 68.0%). The rest of the hyperparameters — learning rate, LoRA
  rank — were **not** searched.
- Latency was measured on a Colab T4 for the models and on a local CPU for the regex.
  The 0.001 s vs 8.93 s gap is real in magnitude but the two numbers come from different
  hardware and are not a controlled comparison.
- 160 records is modest. Enough for a narrow LoRA fine-tune, not enough for broad claims.
- Some issuers appear as preliminary/final pairs of the same offering (Allstate, Bank of
  Hawaii, Boeing, Strategy). Not leakage — both sides of a pair sit in the same split — but
  those offerings carry double weight in the metric.
- Labels were drafted by an LLM and reviewed by a human against the filing text. They are
  not audited line by line.
- `issuer_name` was deliberately removed from the extraction schema. It is absent from 26%
  of spans, and where a company name does appear it is sometimes the external adviser rather
  than the issuer (the Gladstone filing names "Gladstone Management Corporation, the external
  adviser"). EDGAR supplies the issuer deterministically in metadata; extracting it from
  trap-laden prose is the wrong design.
- **Three green scanner badges are not "no vulnerabilities".** Measured on `2c8b675`:
  CodeQL (`security-extended`, 50 rules) reported **0 results** over the 25 Python files it
  extracted; pip-audit found 0 advisories across the 57 packages the declared stack resolves
  to and the 76 the CI environment installed; gitleaks found 0 secrets across 47 commits.
  What that does *not* establish: the path-traversal finding this project fixed by hand
  (`C-01`, commit `37bc129`) is a class of bug these queries would **not** have raised — and
  that was measured, not assumed. The same CodeQL CLI (2.26.3) and the same 50-rule suite were
  run locally against two databases: a deliberately vulnerable file (Flask `request.args` →
  `open()`) produced **2 `py/path-injection` findings**, and this repository at the pre-fix
  commit `6e26931`, with `C-01` still live, produced **0**. The query works; the gap is source
  modelling. `py/path-injection` draws from `ActiveThreatModelSource`, and CodeQL's
  `Requests.qll` models `requests` only as an *outgoing* client call, so a value read out of an
  HTTP **response** is never tainted. The tools narrow the blind spot; they do not close it.
  Nothing here scans the notebook, the Colab base image, or the model weights.
- Design documents under `schema/` are written in Turkish.

## Layout

```
src/edgar.py            EDGAR access — self-identifying UA, 0.25s throttle
src/collect.py          collection, anchor location, offering dedup, loss audit
src/clean_dataset.py    applies data/exclusions.json, sweeps orphan spans
src/split.py            company-wise deterministic split
src/normalize_labels.py fixes the label key set; refuses to guess
src/validate_labels.py  consistency checks
src/review_test.py      human-review table + evidence dump
src/prompt.py           the extraction instruction — ONE source for training and eval
src/build_sft.py        builds data/processed/sft_{train,test}.jsonl
src/measure_tokens.py   token distribution and the seq_len decision
src/extract_rules.py    rule-based contestant, developed on train only
src/evaluate.py         the measurement harness — written before any model ran
src/train_lora.py       LoRA SFT — API verified against current docs, CPU smoke-tested
src/predict.py          generation -> raw model output for the harness
COLAB.md                free-tier T4 runbook: fine-tune and measure at zero cost
schema/                 extraction schema and labelling spec
tests/                  145 tests over real filing excerpts and the CI workflows (2026-08-19)
data/interim/labels/    160 gold records — hand-produced, the one thing code cannot regenerate
data/interim/spans/     the cover-page excerpt each record was labelled from (~6 KB each)
data/interim/manifest.json    accession -> company/CIK/URL; the company-wise split rests on it
data/exclusions.json    tracked exclusion list with reasons
data/dev_split.json     tracked dev carve (companies + accessions) — selection must be reproducible
data/company_keys_extra.json  tracked company keys for 3 records absent from the manifest
```

`src/prompt.py` is deliberately a single module. Step 3 pits a fine-tuned small model against
a prompted large model and a rule-based regex extractor; if each kept its own copy of the
instruction, one would drift and the comparison would quietly measure prompt quality instead
of model quality.

## Data and licensing

Code is MIT. SEC filings are public record. **Full documents are not redistributed** — they are
fetched at runtime into gitignored directories. What *is* tracked is the labelled dataset: the
gold JSON records under `data/interim/labels/`, and under `data/interim/spans/` the cover-page
excerpt each was labelled from (~6 KB per filing, out of documents that run to 400 KB). Every
span carries its accession number, so any value can be checked against the original on EDGAR.
This is the same standard the test fixtures already hold themselves to — real excerpts from real
filings, cited. Access follows SEC fair-access rules: a self-identifying User-Agent (never
rotated) and request throttling.
