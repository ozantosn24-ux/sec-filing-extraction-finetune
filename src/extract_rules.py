"""Kural-tabanli cikarici — adim ③'un UCUNCU yarismacisi.

Bu, PrefEdge'in `edgar_parser.py`'inin *"left as None for now"* diye biraktigi isin
durustce denenmis hali. Iki sarti var:

1. **Adam-korkuluk OLMAYACAK.** Kasten zayif bir baseline, fine-tuned modelin
   zaferini uydurur. Her alan icin makul en iyi kural yazildi.
2. **TEST'E BAKILARAK AYARLANMAYACAK.** Kurallar yalnizca `train` uzerinde
   gelistirildi (`--split train`). Test'e bir kez, son halinde bakilir. Aksi
   halde baseline test'e sizar ve karsilastirma yalan olur.

Girdiyi `prompt.normalize_span` uzerinden alir — uc yarismaci da AYNI metni gorur.
(U+200B olculdu: 1.937 adet. `\\s+` onu tutmuyor; temizlenmeseydi tam bu script
sessizce sakat kalirdi.)

Kullanim:
    python src/extract_rules.py --split train        # gelistirme
    python src/extract_rules.py --split test -o preds_regex.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from prompt import normalize_span

ROOT = Path(__file__).resolve().parent.parent
SPAN_DIR = ROOT / "data" / "interim" / "spans"

FIELD_ORDER = [
    "series", "coupon_rate_pct", "offered_unit", "depositary_ratio",
    "liquidation_preference_usd", "par_value_usd", "cumulative", "redeemable",
    "convertible", "perpetual", "shares_offered", "dividend_frequency", "is_preliminary",
]

COUPON_MIN, COUPON_MAX = 2.0, 15.0


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def series(t: str) -> str | None:
    # Basliktaki seri harfi. "Series H Preferred" / "Class F Cumulative".
    m = re.search(r"\b(?:Series|Class)\s+([A-Z]{1,2})\b", t)
    return m.group(1) if m else None


def coupon(t: str) -> float | None:
    # Kupon BASLIKTA gecer ve menkul kiymet adiyla bitisiktir. Serbest gezen
    # yuzdeler kredi faizi/komisyon olabiliyor (olculdu: UMH 1.50-2.20% kredi
    # marji), o yuzden kalip menkul kiymet kelimeleriyle demirleniyor.
    for m in re.finditer(r"(\d{1,2}(?:\.\d{1,4})?)\s*%\s*"
                         r"(?=[^.\n]{0,60}?(?:Series|Class|Cumulative|Non-Cumulative|"
                         r"Perpetual|Fixed|Preferred))", t):
        v = float(m.group(1))
        if COUPON_MIN <= v <= COUPON_MAX:
            return v
    return None


def offered_unit(t: str) -> str | None:
    if re.search(r"[Dd]epositary\s+[Ss]hares?", t):
        return "depositary_share"
    if re.search(r"[Pp]referred\s+[Uu]nits?", t):
        return "unit"
    if re.search(r"per\s+Note\b|[Nn]otes\s+due\s+\d{4}", t):
        return "note"
    if re.search(r"[Pp]referred\s+(?:[Ss]tock|[Ss]hares)", t):
        return "share"
    return None


def depositary_ratio(t: str) -> int | None:
    m = re.search(r"1\s*/\s*([\d,]+)\s*(?:st|nd|rd|th)?\s+interest", t, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def liquidation(t: str, unit: str | None = None) -> float | None:
    """Sirasi ONEMLI — olculdu (train): yanlis sira %63,7, dogru sira %83,9.

    1) Birim depositary ise "per Depositary Share" fiyati ONCE aranir. Aksi halde
       kural altta yatan imtiyazli hissenin $1.000'ini kapiyordu (train'de 14 kayit):
       tam da LABELING.md §F'nin "buyuk rakama yonelme" diye tarif ettigi hata.
    2) Acik "liquidation preference" ifadesi; "equivalent to $X" varsa O alinir,
       cunku teklif edilen birim basina olan odur.
    3) Ifade hic gecmiyorsa hisse basi teklif fiyati tasfiye tercihidir
       (LABELING.md §A) — ama "par value $0.01 per share" ELENIR, yoksa kural
       par degerini tasfiye tercihi sanar (train'de 6 kayit).
    """
    if unit == "depositary_share":
        m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s+per\s+[Dd]epositary\s+[Ss]hare", t)
        if m:
            return _num(m.group(1))
    m = re.search(r"[Ll]iquidation\s+[Pp]reference\s+(?:of\s+)?\$\s*([\d,]+(?:\.\d+)?)"
                  r"(?:[^.\n]{0,80}?equivalent\s+to\s+\$\s*([\d,]+(?:\.\d+)?))?", t)
    if m:
        return _num(m.group(2) or m.group(1))
    for m in re.finditer(r"\$\s*([\d,]+(?:\.\d+)?)\s+per\s+"
                         r"(?:[Dd]epositary\s+[Ss]hare|share|unit)", t):
        if re.search(r"par\s+value\s*(?:of\s*)?$", t[max(0, m.start() - 30):m.start()], re.I):
            continue
        return _num(m.group(1))
    return None


def par_value(t: str) -> float | None:
    if re.search(r"\b(?:no|without)\s+par\s+value", t, re.I):
        return None  # "par degeri yok" = tutar YOK, 0.00 DEGIL (LABELING.md §H)
    m = re.search(r"par\s+value\s+(?:of\s+)?\$\s*([\d.]+)", t, re.I)
    return float(m.group(1)) if m else None


def _bool_explicit(t: str, kelime: str, olumsuz: str | None = None) -> bool | None:
    """Sessizlikten `false` URETME (LABELING.md §G): yoksa null."""
    if olumsuz and re.search(olumsuz, t):
        return False
    if re.search(kelime, t):
        return True
    return None


def shares_offered(t: str) -> int | None:
    # Kapaktaki adet, birim kelimesinin hemen onunde durur.
    m = re.search(r"([\d]{1,3}(?:,\d{3})+)\s+(?:[Dd]epositary\s+[Ss]hares?|"
                  r"[Ss]hares?|[Pp]referred\s+[Uu]nits?)", t)
    return int(m.group(1).replace(",", "")) if m else None


def dividend_frequency(t: str) -> str | None:
    if re.search(r"[Mm]onthly", t):
        return "monthly"
    if re.search(r"quarterly", t, re.I):
        return "quarterly"
    if re.search(r"semi-?annual", t, re.I):
        return "semi-annual"
    if re.search(r"\bannually\b", t, re.I):
        return "annual"
    return None


def is_preliminary(t: str) -> bool:
    return bool(re.search(r"[Ss]ubject\s+to\s+[Cc]ompletion|"
                          r"[Pp]reliminary\s+[Pp]rospectus\s+[Ss]upplement", t))


def extract(span: str) -> dict:
    t = normalize_span(span)
    unit = offered_unit(t)
    return {
        "series": series(t),
        "coupon_rate_pct": coupon(t),
        "offered_unit": unit,
        "depositary_ratio": depositary_ratio(t) if unit == "depositary_share" else None,
        "liquidation_preference_usd": liquidation(t, unit),
        "par_value_usd": par_value(t),
        # Kalip genisligi train uzerinde OLCULDU; harfi harfine kalip ciddi bir
        # baseline degil, adam-korkuluk olurdu:
        #   redeemable  "Redeemable" tek basina %46 -> "redemption|redeem" ile %96
        #   perpetual   "Perpetual"  tek basina %77 -> "no (stated) maturity" ile %94
        #   convertible dar kalip    %78            -> genis "conversion" ile %88
        # Sebep: etiketciler kelimeyi degil ANLAMI okumus — "we may redeem ..."
        # diyen belgede "Redeemable" kelimesi hic gecmiyor ama alan dogru sekilde True.
        "cumulative": _bool_explicit(t, r"[Cc]umulative", r"Non-[Cc]umulative|non-cumulative"),
        "redeemable": _bool_explicit(t, r"[Rr]edeemable|[Rr]edemption|\bredeem\b"),
        "convertible": _bool_explicit(t, r"[Cc]onvertible|conversion",
                                      r"not\s+convertible|no\s+conversion\s+rights"),
        "perpetual": _bool_explicit(t, r"[Pp]erpetual|no\s+(?:stated\s+)?maturity"),
        "shares_offered": None if unit == "note" else shares_offered(t),
        "dividend_frequency": dividend_frequency(t),
        "is_preliminary": is_preliminary(t),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=("train", "dev", "test"))
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()

    # `dev` train'den SIRKET bazinda oyuldu ama span dosyalari train/ altinda
    # kaldi; bolme bir dosya dizini degil accession listesi. Ayni sebeple
    # `train` dev'i disliyor — iki bolme ayni kaydi sayarsa karsilastirma bozulur.
    dev_file = ROOT / "data" / "dev_split.json"
    dev_acc: set[str] = set()
    if dev_file.exists():
        dev_acc = set(json.loads(dev_file.read_text(encoding="utf-8"))["accessions"])
    elif args.split == "dev":
        raise SystemExit(f"{dev_file} yok — once `python src/build_sft.py`")

    span_dir = SPAN_DIR / ("train" if args.split == "dev" else args.split)

    rows = []
    for p in sorted(span_dir.glob("*.txt")):
        if args.split == "dev" and p.stem not in dev_acc:
            continue
        if args.split == "train" and p.stem in dev_acc:
            continue
        span = p.read_text(encoding="utf-8")
        t0 = time.perf_counter()
        obj = extract(span)
        dt = time.perf_counter() - t0
        rows.append({
            "accession": p.stem,
            # Yapisi geregi gecerli JSON uretir; sema gecerliligi metriginde
            # %100 almasi BEKLENIR ve bu bir avantaj degil, yontemin tanimi.
            "raw": json.dumps({f: obj[f] for f in FIELD_ORDER}, ensure_ascii=False),
            "latency_s": round(dt, 6),
            "model": "regex-rules",
        })

    out = (args.out or ROOT / "data" / "processed" / f"preds_regex_{args.split}.jsonl").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} tahmin -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
