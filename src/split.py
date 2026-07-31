"""Train/test bolmesi — BELGE degil SIRKET bazinda.

Ayni sirketin belgeleri iki tarafa dagilirsa model sirketin kalip metnini
ezberler ve eval siser. Olculdu: 87 belge / 53 sirket, SCE tek basina 10 belge.
Bolme deterministik (sabit tohum) — tekrar calistirildiginda ayni sonuc.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN_FILE = ROOT / "data" / "interim" / "documents.jsonl"
SPAN_DIR = ROOT / "data" / "interim" / "spans"
MANIFEST = ROOT / "data" / "interim" / "manifest.json"

TEST_FRACTION = 0.25
SEED = "edgar-extract-v1"


def bucket(company_key: str) -> str:
    """Sirket adindan deterministik kova. Rastgelelik yok -> tekrar uretilebilir."""
    h = hashlib.sha256(f"{SEED}:{company_key}".encode()).hexdigest()
    return "test" if int(h[:8], 16) / 0xFFFFFFFF < TEST_FRACTION else "train"


def main() -> int:
    docs = [json.loads(l) for l in IN_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]

    by_company: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        by_company[d["company_key"]].append(d)

    assignment = {c: bucket(c) for c in by_company}
    manifest: dict[str, list[dict]] = {"train": [], "test": []}

    for company, split in assignment.items():
        for d in by_company[company]:
            out = SPAN_DIR / split / f"{d['accession']}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(d["span"], encoding="utf-8")
            manifest[split].append(
                {
                    "accession": d["accession"],
                    "company": d["company"],
                    "company_key": d["company_key"],
                    "filed_date": d["filed_date"],
                    "anchor": d["anchor"],
                    "doc_url": d["doc_url"],
                    "span_file": str(out.relative_to(ROOT)).replace("\\", "/"),
                }
            )

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    overlap = {m["company_key"] for m in manifest["train"]} & {
        m["company_key"] for m in manifest["test"]
    }
    print(f"train: {len(manifest['train']):>3} belge / "
          f"{len({m['company_key'] for m in manifest['train']})} sirket")
    print(f"test : {len(manifest['test']):>3} belge / "
          f"{len({m['company_key'] for m in manifest['test']})} sirket")
    for split in ("train", "test"):
        prelim = sum(1 for m in manifest[split] if m["anchor"] == "preliminary")
        print(f"  {split} on-prospektus (abstention): {prelim}")
    print(f"\nSIRKET ORTUSMESI: {len(overlap)}  <- 0 olmali (sizinti kontrolu)")
    return 0 if not overlap else 1


if __name__ == "__main__":
    raise SystemExit(main())
