"""Etiket SEKLINI sabitle — 13 anahtar, her kayitta, ayni sirada.

NEDEN (2026-07-31 olcumu): 161 etiketin 42'sinde `offered_unit`, 44'unde
`depositary_ratio` anahtari HIC YOKTU (null degil, YOK). Bunlar birinci dalga
etiketleri; alanlar ikinci dalgada eklendi.

Bu, egitim icin sessiz bir bozukluk:
  - hedef JSON'un anahtar kumesi kayittan kayida degisirse model TUTARSIZ bir
    cikti sekli ogrenir;
  - "sema gecerliligi" metrigi tanimsizlasir — neyin gecerli oldugu sabit degil.

## Turetme kurali (uydurma DEGIL, metne dayali)

Eksik `offered_unit` icin span'e bakilir:

  1. Kapakta depositary-hisse YAPISI varsa  -> COZULMEDI, operatore birakilir.
     (Deger uydurmak yerine durur. Su an bu dala dusen kayit yok; kural
     ileride yeni veri geldiginde sessizce yanlis etiket uretmesin diye var.)
  2. Ortaklik (LP) "Preferred Units" ihraci ise -> "unit", ratio null.
  3. Yoksa ama imtiyazli hisse ihraci ifadesi varsa -> "share", ratio null.
     Dayanak metnin YOKLUGU degil, VARLIGI: depositary yapisi kapak sayfasinda
     her zaman aciktan yazilir ("Depositary Shares, each representing a
     1/1,000th interest"), gecmiyorsa yapi yoktur.
  4. Hicbiri yoksa -> COZULMEDI.

⚠️ Aranan sey "depositary" KELIMESI degil, `depositary share|interest` KALIBI.
Olculdu: uc kayitta "depositary" yalnizca adi hisseye ait kontrol-degisikligi
cumlesinde geciyor ("...or American Depositary Receipts (ADRs) representing such
securities..."). Dar kalip bunlari zaten tutmuyor.

📌 ADR/ADS ifadesini metinden AYIKLAYAN bir on-temizlik once vardi, KALDIRILDI
(mutasyon denetimi 2026-07-31): gozlemlenmemis bir durumu koruyordu ve zararliydi.
Korpusta "American Depositary Share" gecen belge YOK (0/160); geldiginde de dogru
davranis onu ayiklamak DEGIL, durmaktir — ADS gercekten depositary-benzeri bir
birimdir. Ayiklamak, operatorun okumasi gereken bir vakayi sessizce "share" yapardi.
Kural: gozlemlenmemis durumda TAHMIN degil DURUS.

Script IDEMPOTENT: zaten dolu olan alana dokunmaz, iki kez kosmak guvenlidir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL_DIR = ROOT / "data" / "interim" / "labels"
SPAN_DIR = ROOT / "data" / "interim" / "spans"
REPORT = ROOT / "data" / "interim" / "normalize_report.json"

# Hedef JSON'un KANONIK anahtar sirasi. Egitim hedefi de, eval karsilastirmasi da
# bu sirayi kullanir; sira sabit olmazsa tam-eslesme metrigi string duzeyinde saglam olmaz.
FIELD_ORDER = [
    "series", "coupon_rate_pct", "offered_unit", "depositary_ratio",
    "liquidation_preference_usd", "par_value_usd", "cumulative", "redeemable",
    "convertible", "perpetual", "shares_offered", "dividend_frequency", "is_preliminary",
]

# Kapakta gercek depositary YAPISI. Kalip DAR olmali: yalin "depositary" kelimesi
# ADR cumlesinde de geciyor ve genis kalip uc kaydi yanlis dala dusururdu.
DEPOSITARY_STRUCT = re.compile(r"depositary\s+(?:share|interest)", re.I)
# LP ihraclari "Preferred Unit" satar; hisse degildir (temettu degil DAGITIM oder).
# Olculdu: korpusta 1 belge (Energy Transfer LP) — gozlemlenmis kenar durum, uydurma degil.
PREFERRED_UNIT = re.compile(r"preferred\s+units?\b", re.I)
PREFERRED_OFFERING = re.compile(r"preferred\s+(?:stock|shares?|securities)", re.I)


def derive_unit(span: str) -> tuple[str | None, str]:
    """(offered_unit, gerekce). Karar veremezse (None, gerekce) doner."""
    clean = span
    if DEPOSITARY_STRUCT.search(clean):
        return None, "span'de depositary YAPISI var — birim/oran elle okunmali"
    if PREFERRED_UNIT.search(clean):
        return "unit", "ortaklik (LP) imtiyazli UNIT ihraci"
    if PREFERRED_OFFERING.search(clean):
        return "share", "depositary yapisi yok + imtiyazli hisse ifadesi var"
    return None, "ne depositary yapisi ne imtiyazli hisse ifadesi bulundu"


def main() -> int:
    derived: list[dict] = []
    unresolved: list[dict] = []
    reordered = 0
    untouched = 0

    for split in ("train", "test"):
        for p in sorted((LABEL_DIR / split).glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            acc = p.stem
            missing = [f for f in FIELD_ORDER if f not in d]

            if missing:
                span_file = SPAN_DIR / split / f"{acc}.txt"
                span = span_file.read_text(encoding="utf-8") if span_file.exists() else ""

                if "offered_unit" in missing:
                    unit, why = derive_unit(span)
                    if unit is None:
                        unresolved.append({"split": split, "accession": acc, "neden": why})
                        continue
                    d["offered_unit"] = unit
                    derived.append({"split": split, "accession": acc,
                                    "alan": "offered_unit", "deger": unit, "gerekce": why})

                if "depositary_ratio" in missing:
                    # Birim depositary DEGILSE oran tanimsizdir -> null. Depositary ise
                    # yukaridaki dal zaten durdurmus olurdu.
                    d["depositary_ratio"] = None
                    derived.append({"split": split, "accession": acc,
                                    "alan": "depositary_ratio", "deger": None,
                                    "gerekce": f"offered_unit={d['offered_unit']} — oran tanimsiz"})

            ordered = {f: d.get(f) for f in FIELD_ORDER}
            ordered["evidence"] = d.get("evidence") or {}

            extra = [k for k in d if k not in FIELD_ORDER and k != "evidence"]
            if extra:
                unresolved.append({"split": split, "accession": acc,
                                   "neden": f"semada olmayan alan: {extra}"})
                continue

            new = json.dumps(ordered, ensure_ascii=False, indent=2)
            if new != p.read_text(encoding="utf-8").rstrip("\n"):
                p.write_text(new, encoding="utf-8")
                reordered += 1
            else:
                untouched += 1

    print(f"TURETILEN alan : {len(derived)}")
    by_field: dict[str, int] = {}
    for r in derived:
        by_field[r["alan"]] = by_field.get(r["alan"], 0) + 1
    for f, n in sorted(by_field.items()):
        print(f"   {f:<20} {n}")
    print(f"YAZILAN dosya  : {reordered}  (degismeyen {untouched})")
    print(f"COZULMEYEN     : {len(unresolved)}  <- ELLE okunmali, uydurulmadi")
    for r in unresolved:
        print(f"   {r['split']}/{r['accession']}: {r['neden']}")

    REPORT.write_text(json.dumps({"turetilen": derived, "cozulmeyen": unresolved},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nrapor -> {REPORT.relative_to(ROOT)}")
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
