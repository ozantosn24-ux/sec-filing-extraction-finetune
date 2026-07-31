# edgar-extract

Structured field extraction from SEC 424B5 preferred-stock prospectuses, built to
measure one question: **can a small fine-tuned model beat a large prompted model on
schema-strict extraction, on cost, latency and format adherence?**

The task is not invented for a demo. A rule-based parser I wrote earlier
(`prefedge/backend/utils/edgar_parser.py`) gives up on exactly these fields:

> `Coupon/par/issue_size require fetching the full prospectus — left as None for now.`

Those values sit in dense legal prose on the cover page. Keyword matching does not
recover them reliably. This repository builds the dataset and the measurement.

## Status

| stage | state |
|---|---|
| 1. Dataset | **done** — 76 labelled records, all consistency checks pass |
| 2. LoRA fine-tune (PyTorch) | not started |
| 3. Evaluation vs prompted baseline | not started |

Nothing here claims a result yet. The dataset is the part that exists.

## Dataset

| split | documents | companies | abstention cases |
|---|---|---|---|
| train | 62 | 34 | 21 |
| test | 14 | 10 | 4 |

**Company-wise split, zero company overlap.** Some issuers file repeatedly — Southern
California Edison appeared 10 times, State Street 9. A random document-level split would
put the same issuer's boilerplate on both sides and inflate the score.

**Abstention slice (25 records).** Preliminary prospectuses are filed before pricing, so
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
consistency check. The distribution before and after says it plainly:

| liquidation preference | before | after |
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

```bash
export SEC_EDGAR_UA="Your Name your@email.com"   # SEC requires a self-identifying UA
python src/collect.py --per-query 10 --max-docs 250
python src/clean_dataset.py     # applies data/exclusions.json
python src/split.py             # company-wise, deterministic
python src/validate_labels.py   # consistency checks
pytest -q
```

`data/exclusions.json` is tracked and lists 11 accessions that `collect.py` retrieves but
which are not preferred-stock offerings (base prospectuses, common-stock ATM programmes,
resale registrations), each with a reason. Without it the pipeline is not reproducible —
a fresh clone would produce 87 records instead of 76.

## Tests

```
pytest -q     # 17 tests
```

Fixtures under `tests/fixtures/` are **real excerpts from real filings**, each carrying its
accession number and source URL. No invented examples: every bug this project found came
from real documents, not from imagined ones. The tests were mutation-checked — reverting
the whitespace normaliser, the coupon range validation or the search bound each turns a
test red.

## Known limitations

- 76 records is small. Enough for a narrow LoRA fine-tune, not enough for broad claims.
- Test set is 14 documents but roughly 10 distinct offerings — Allstate, Bank of Hawaii,
  Boeing and Strategy each appear as a preliminary/final pair. Not leakage (both sides of a
  pair sit in test), but those offerings carry double weight in the metric.
- Labels were drafted by an LLM and reviewed by a human against the filing text. They are
  not audited line by line.
- `issuer_name` was deliberately removed from the extraction schema. It is absent from 26%
  of spans, and where a company name does appear it is sometimes the external adviser rather
  than the issuer (the Gladstone filing names "Gladstone Management Corporation, the external
  adviser"). EDGAR supplies the issuer deterministically in metadata; extracting it from
  trap-laden prose is the wrong design.
- Design documents under `schema/` are written in Turkish.

## Layout

```
src/edgar.py            EDGAR access — self-identifying UA, 0.25s throttle
src/collect.py          collection, anchor location, offering dedup, loss audit
src/clean_dataset.py    applies data/exclusions.json
src/split.py            company-wise deterministic split
src/validate_labels.py  consistency checks
src/review_test.py      human-review table + evidence dump
schema/                 extraction schema and labelling spec
tests/                  17 tests over real filing excerpts
data/exclusions.json    tracked exclusion list with reasons
```

## Data and licensing

Code is MIT. SEC filings are public record and are **not** redistributed here — documents are
fetched at runtime into gitignored directories. Access follows SEC fair-access rules: a
self-identifying User-Agent (never rotated) and request throttling.
