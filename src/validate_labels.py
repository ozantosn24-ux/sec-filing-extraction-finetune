"""Etiket kalitesi denetimi — sayaclara degil ICERIGE bak.

Etiketler taslak; bu script guvenilmez kayitlari ISARETLER, silmez.
Karar operatorde kalir.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL_DIR = ROOT / "data" / "interim" / "labels"
SPAN_DIR = ROOT / "data" / "interim" / "spans"
FLAG_FILE = ROOT / "data" / "interim" / "label_flags.json"

FIELDS = [
    "issuer_name", "series", "coupon_rate_pct", "offered_unit", "depositary_ratio",
    "liquidation_preference_usd", "par_value_usd", "cumulative", "redeemable",
    "convertible", "perpetual", "shares_offered", "dividend_frequency", "is_preliminary",
]

# Gercek imtiyazli ihraclarin buyuklugu bu araliktadir. Disina cikan carpim
# neredeyse her zaman BIRIM KARISIKLIGIdir (depositary hisse x alttaki tercih).
MIN_OFFERING_USD = 10_000_000
MAX_OFFERING_USD = 5_000_000_000


def load() -> list[tuple[str, str, dict]]:
    out = []
    for split in ("train", "test"):
        for p in sorted((LABEL_DIR / split).glob("*.json")):
            try:
                out.append((split, p.stem, json.loads(p.read_text(encoding="utf-8"))))
            except json.JSONDecodeError as exc:
                print(f"  BOZUK JSON: {split}/{p.name}: {exc}")
    return out


def main() -> int:
    rows = load()
    print(f"etiket: {len(rows)} (train {sum(1 for r in rows if r[0]=='train')}, "
          f"test {sum(1 for r in rows if r[0]=='test')})\n")

    print("ALAN DOLULUK ORANI")
    for f in FIELDS:
        filled = sum(1 for _, _, d in rows if d.get(f) is not None)
        pct = filled / len(rows) * 100
        bar = "#" * int(pct / 4)
        print(f"  {f:<28}{filled:>3}/{len(rows)} {pct:>5.1f}% {bar}")

    flags: dict[str, list[str]] = {}

    def flag(acc: str, why: str) -> None:
        flags.setdefault(acc, []).append(why)

    print("\nTUTARLILIK KONTROLLERI")

    # 1) kupon makul araligi
    bad_coupon = [(a, d["coupon_rate_pct"]) for _, a, d in rows
                  if d.get("coupon_rate_pct") is not None
                  and not (2.0 <= float(d["coupon_rate_pct"]) <= 15.0)]
    print(f"  kupon 2-15% disinda            : {len(bad_coupon)}")
    for a, v in bad_coupon:
        flag(a, f"kupon {v} makul disi")

    # 2) par == liq  -> spec'teki EN SIK hata
    confused = [a for _, a, d in rows
                if d.get("par_value_usd") is not None
                and d.get("liquidation_preference_usd") is not None
                and float(d["par_value_usd"]) == float(d["liquidation_preference_usd"])]
    print(f"  par == liquidation (karisiklik) : {len(confused)}")
    for a in confused:
        flag(a, "par_value == liquidation_preference")

    # 3) liq pref dagilimi — imtiyazlida beklenen 25 / 100 / 1000 / 25000
    liq = Counter(float(d["liquidation_preference_usd"]) for _, _, d in rows
                  if d.get("liquidation_preference_usd") is not None)
    print(f"  liquidation_preference dagilimi : "
          f"{', '.join(f'{v}={n}' for v, n in sorted(liq.items())[:8])}")

    # 3b) BIRIM ESLESTIRMESI — en pahali hata. shares x liq_pref makul mu?
    unit_bad = []
    for _, a, d in rows:
        sh, lq = d.get("shares_offered"), d.get("liquidation_preference_usd")
        if sh is None or lq is None:
            continue
        total = float(sh) * float(lq)
        if not (MIN_OFFERING_USD <= total <= MAX_OFFERING_USD):
            unit_bad.append((a, sh, lq, total))
    print(f"  BIRIM KARISIKLIGI (shares x liq)  : {len(unit_bad)}  <- carpim makul ihrac disi")
    for a, sh, lq, total in unit_bad[:5]:
        print(f"     {a} {sh:,} x {lq:,.0f} = ${total:,.0f}")
    for a, sh, lq, total in unit_bad:
        flag(a, f"birim karisikligi: {sh:,} x {lq:,.0f} = ${total:,.0f}")

    # 4) issuer_name yok -> pencere sirket adini kacirmis
    no_issuer = [a for _, a, d in rows if not d.get("issuer_name")]
    print(f"  issuer_name YOK                 : {len(no_issuer)}")
    for a in no_issuer:
        flag(a, "issuer_name yok (pencere sirket adini kacirmis)")

    # 5) on prospektus tutarliligi: is_preliminary=true ama kupon dolu
    prelim_with_coupon = [a for _, a, d in rows
                          if d.get("is_preliminary") and d.get("coupon_rate_pct") is not None]
    print(f"  is_preliminary ama kupon DOLU   : {len(prelim_with_coupon)}")
    for a in prelim_with_coupon:
        flag(a, "is_preliminary=true ama coupon dolu (kural D yorumu ajanlar arasi farkli)")

    # 6) tamamen bos kayitlar -> muhtemelen imtiyazli ihrac degil
    empty = [a for _, a, d in rows
             if sum(1 for f in FIELDS if f != "is_preliminary" and d.get(f) is not None) <= 2]
    print(f"  neredeyse BOS (<=2 alan dolu)   : {len(empty)}  <- muhtemelen ihrac degil")
    for a in empty:
        flag(a, "neredeyse bos — muhtemelen imtiyazli ihrac degil")

    # 7) span dosyasi var mi
    missing = [a for s, a, _ in rows if not (SPAN_DIR / s / f"{a}.txt").exists()]
    if missing:
        print(f"  span dosyasi eksik              : {len(missing)}")

    FLAG_FILE.write_text(json.dumps(flags, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nISARETLENEN KAYIT: {len(flags)}/{len(rows)}  -> {FLAG_FILE.name}")
    print(f"TEMIZ KAYIT       : {len(rows) - len(flags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
