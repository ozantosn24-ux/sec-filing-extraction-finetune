"""Veri seti temizligi — yanlis-pozitifleri cikar, kotu alani sadan dusur.

IKI KARAR (2026-07-31, kanitla):

1) `issuer_name` CIKARIM HEDEFI OLMAKTAN CIKARILDI.
   - span'lerin %26'sinda ihraccinin adi hic gecmiyor
   - gectiginde de tuzak var: Gladstone span'inde "Gladstone" 3 kez geciyor ama
     "Gladstone Management Corporation, the EXTERNAL ADVISER" olarak — ihracci degil
   - EDGAR zaten sirket adini metadata'da kesin veriyor (manifest.company)
   ⇒ Deterministik olarak elde olan bir seyi tuzakli metinden cikarttirmak yanlis
   tasarim. Ad metadata olarak KALIR, cikarim semasindan DUSER.

2) Imtiyazli ihrac OLMAYAN kayitlar cikarilir. Toplayicinin yanlis-pozitifleri;
   dort alt-ajan bagimsiz olarak ayni kayitlari isaretledi (adi hisse ATM'i,
   yeniden satis kaydi, base prospektus, common stock ihraci).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
LABEL_DIR = INTERIM / "labels"
SPAN_DIR = INTERIM / "spans"
DROPPED = INTERIM / "dropped"

DROP_FIELD = "issuer_name"

# Git'te TAKIP EDILEN dislama listesi. Elle silme tekrar-uretilebilir degildi:
# repoyu klonlayip collect.py kosan biri 87 kayit alirdi, 76 degil.
EXCLUSIONS = ROOT / "data" / "exclusions.json"

# Cikarim hedefi olan alanlar (is_preliminary bir bayrak, sayilmaz).
CONTENT_FIELDS = [
    "series", "coupon_rate_pct", "offered_unit", "depositary_ratio",
    "liquidation_preference_usd", "par_value_usd", "cumulative", "redeemable",
    "convertible", "perpetual", "shares_offered", "dividend_frequency",
]
MIN_FILLED = 3


def load_exclusions() -> dict[str, str]:
    if not EXCLUSIONS.exists():
        return {}
    data = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
    return {e["accession"]: e["reason"] for e in data.get("excluded", [])}


def main() -> int:
    dropped: list[tuple[str, str, int]] = []
    kept = 0
    excluded = load_exclusions()
    print(f"dislama listesi: {len(excluded)} accession (data/exclusions.json)")

    for split in ("train", "test"):
        for p in sorted((LABEL_DIR / split).glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))

            filled = sum(1 for f in CONTENT_FIELDS if d.get(f) is not None)
            if p.stem in excluded or filled < MIN_FILLED:
                (DROPPED / split).mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), DROPPED / split / p.name)
                span = SPAN_DIR / split / f"{p.stem}.txt"
                if span.exists():
                    shutil.move(str(span), DROPPED / split / f"{p.stem}.txt")
                dropped.append((split, p.stem, filled))
                continue

            # issuer_name cikarim semasindan duser (metadata'da kaliyor)
            d.pop(DROP_FIELD, None)
            if isinstance(d.get("evidence"), dict):
                d["evidence"].pop(DROP_FIELD, None)
            p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            kept += 1

    print(f"KORUNAN : {kept}")
    print(f"CIKARILAN: {len(dropped)}  -> data/interim/dropped/ (silinmedi, tasindi)")
    for split, acc, n in dropped:
        print(f"   {split}/{acc}  ({n} alan dolu)")

    # OKSUZ SPAN SUPURGESI. Cikarma bir kez yapilir ama span uretimi yeniden
    # kosulabilir; kosulunca cikarilmis accession'larin span'i geri gelir ve
    # spans/ ile labels/ birbirini tutmaz. Olculdu: 10 oksuz span.
    # Etiket kaynak-i hakikat oldugu icin bunlar egitim setine SIZMAZ; yine de
    # sessiz tutarsizlik birakmamak icin supuruluyor.
    orphans, unexpected = [], []
    for split in ("train", "test"):
        for sp in sorted((SPAN_DIR / split).glob("*.txt")):
            if (LABEL_DIR / split / f"{sp.stem}.json").exists():
                continue
            known = sp.stem in excluded or (DROPPED / split / f"{sp.stem}.json").exists()
            if known:
                (DROPPED / split).mkdir(parents=True, exist_ok=True)
                shutil.move(str(sp), DROPPED / split / sp.name)
                orphans.append(f"{split}/{sp.stem}")
            else:
                unexpected.append(f"{split}/{sp.stem}")

    print(f"OKSUZ SPAN: {len(orphans)} tasindi (cikarilmis kayitlarin yeniden uretilmis span'leri)")
    if unexpected:
        print(f"  UYARI: BEKLENMEYEN oksuz span: {len(unexpected)} — etiketi YOK ve cikarilmamis, ELLE bak:")
        for o in unexpected:
            print(f"     {o}")
    print(f"\n'{DROP_FIELD}' alani {kept} etiketten kaldirildi (metadata olarak manifest'te kaliyor)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
