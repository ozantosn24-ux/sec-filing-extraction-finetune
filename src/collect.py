"""Veri seti toplayici — 424B5 imtiyazli hisse prospektuslerini topla, kapak penceresini cikar.

Tasarim kararlari OLCUMDEN turedi (2026-07-31, bkz. schema/preferred_offering.md):

  * Alaka siralamali tek sorgu ornekleme icin UYGUN DEGIL — eski ve temsili olmayan
    belgeler donuyordu. Cok sorgu + tarih penceresi + sayfalama ile taraniyor.
  * forms=424B5 filtresi SIZIYOR (EX-FILING FEES donuyor) -> elde dogrulaniyor.
  * Kisa tadil belgeleri (2-5K karakter) ile asil prospektus (36-395K) ayrimi
    uzunlukla temiz yapiliyor -> MIN_SUBSTANTIVE_CHARS.
  * SABIT KAPAK PENCERESI YETMIYOR. Ilk olcum (n=8) tum terimleri ilk 3.4K'da
    buldu, ama genis orneklemde 29/160 belge (%18) uzun "Table of Contents" ile
    basliyor ve baslik 6.000'in otesine itiliyor. -> sabit pencere yerine
    BASLIK KALIBINI KONUMLANDIR, penceleyi onun etrafina kur.
  * Ayni sirket cok kez geciyor (SCE 10x, State Street 9x) -> train/test bolmesi
    BELGE degil SIRKET bazinda yapilmali; `company` alani bunun icin tasiniyor.
  * Ayni ihracin on/nihai surumleri ayri kayit oluyor -> `offering_key` ile daralt.

Cikti: data/interim/documents.jsonl (her satir bir belge + konumlandirilmis pencere)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edgar import EdgarError, FilingHit, fetch_document, search  # noqa: E402
from explore_one import strip_html  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "interim"
OUT_FILE = OUT_DIR / "documents.jsonl"
REJECT_FILE = OUT_DIR / "rejected.jsonl"

# Reddedilen belgede YINE DE guclu imtiyazli sinyali var mi? (kayip olcumu)
# Sadece kazanci olcup kaybi olcmemek "exit 0 ama veri yanlis" sinifidir.
STRONG_PREF_RE = re.compile(
    r"(?:Series|Class)\s+[A-Z]{1,2}[^\n]{0,80}?Preferred\s+(?:Stock|Shares)", re.I
)
LIQ_RE = re.compile(r"Liquidation\s+Preference", re.I)

# Kisa tadil <-> asil belge esigi. Olculdu: 2.096/3.549/4.117/4.688 vs 36.038/45.937/395.318
MIN_SUBSTANTIVE_CHARS = 20_000

# Konumlandirilan baslik etrafindaki pencere (once/sonra).
SPAN_BEFORE = 800
SPAN_AFTER = 5_200

# OLCULDU: gercek ihrac basligi KAPAK sayfasinda, yani erken. Dagilim cift tepeli —
# 57 belge 0-2.000 arasinda (dogru), derin eslesmeler ise capraz kanit gosterdi:
# UMH @50.711 "1.50% to 2.20% (depending on our overall leverage ratio)" = KREDI FAIZI,
# WesBanco @68.336 oy hakki metni, Babcock @64.418 jenerik kalip. -> arama penceresi sinirli.
SEARCH_LIMIT = 20_000

# Kupon + Preferred. Arada seri/sinif adi olabilir ama satir atlamaz.
TITLE_RE = re.compile(
    r"(\d{1,2}(?:\.\d{1,4})?)\s*%[^\n]{0,120}?\bPreferred\b", re.I
)
# Imtiyazli kuponlarin makul araligi. Disinda kalan eslesme kredi faizi / oran metni.
COUPON_MIN, COUPON_MAX = 2.0, 15.0

# "American Depositary Shares" imtiyazli DEGIL, tamamen baska enstruman (Biodexa ADS).
ADS_RE = re.compile(r"American\s+Depositary\s+Share", re.I)

# OLCULDU: fiyatlama ONCESI on prospektuslerde kupon BOS birakiliyor —
# Synchrony "a share of our % Fixed Rate Reset ... Preferred Stock, Series B",
# LuxUrban "Shares % Series A Cumulative Redeemable Preferred Stock".
# Bunlar kayip degil, dogru cevabi null olan ABSTENTION ornekleri.
PRELIM_TITLE_RE = re.compile(
    r"(?:_{2,}|\s)%[^\n]{0,120}?\bPreferred\s+(?:Stock|Shares)\b", re.I
)


def locate_span(text: str) -> tuple[str, int, str] | None:
    """Ihrac basligini bul, etrafina pencere kur. Gecerli baslik yoksa None.

    'Bulamayinca bas pencereyi al' YAPILMAZ — o, imtiyazli olmayan ihraclari
    sessizce veri setine sokuyordu (GameStop, BurgerFi, MP Materials...).
    Doner: (pencere, ofset, "priced" | "preliminary").
    """
    window = text[:SEARCH_LIMIT]
    for m in TITLE_RE.finditer(window):
        try:
            coupon = float(m.group(1))
        except ValueError:
            continue
        if not (COUPON_MIN <= coupon <= COUPON_MAX):
            continue
        if ADS_RE.search(m.group(0)):
            continue
        start = max(0, m.start() - SPAN_BEFORE)
        return text[start : m.start() + SPAN_AFTER], m.start(), "priced"

    # Fiyatlanmamis on prospektus: kupon bos ama ihrac gercek.
    m = PRELIM_TITLE_RE.search(window)
    if m and not ADS_RE.search(m.group(0)):
        start = max(0, m.start() - SPAN_BEFORE)
        return text[start : m.start() + SPAN_AFTER], m.start(), "preliminary"
    return None


def offering_key(company: str, span: str) -> str:
    """Ayni ihracin on/nihai surumlerini ayni kovaya at: sirket + kupon + seri."""
    coupon = re.search(r"(\d{1,2}(?:\.\d{1,4})?)\s*%", span)
    series = re.search(r"\b(?:Series|Class)\s+([A-Z]{1,2})\b", span)
    return "|".join(
        [
            company.split("  (")[0].strip().lower(),
            coupon.group(1) if coupon else "?",
            series.group(1) if series else "?",
        ]
    )

# Imtiyazli ihraclari hedefleyen sorgular. Tek sorgu tek bir kaliba saplaniyor;
# cesitlilik icin farkli adlandirma gelenekleri taraniyor.
QUERIES = [
    '"Cumulative Redeemable Preferred"',
    '"Cumulative Preferred Stock"',
    '"Series A Cumulative"',
    '"Depositary Shares"',
    '"Fixed-to-Floating Rate"',
    '"Liquidation Preference"',
    '"Preferred Stock, par value"',
]

# Tarih pencereleri — tek pencere ust siniri doldurup eskiye kayiyor.
WINDOWS = [
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-06-30"),
    ("2024-07-01", "2024-12-31"),
    ("2025-01-01", "2025-06-30"),
    ("2025-07-01", "2025-12-31"),
    ("2026-01-01", "2026-07-31"),
]


def is_preferred_offering(text: str) -> bool:
    """Kapak penceresi gercekten imtiyazli hisse ihraci mi? (424B5 cogu zaman degil)"""
    low = text.lower()
    return "preferred" in low and ("%" in text or "liquidation" in low)


def collect(limit_per_query: int, max_docs: int) -> list[dict]:
    seen: set[str] = set()
    seen_offering: set[str] = set()
    docs: list[dict] = []
    rejects: list[dict] = []
    stats = {
        "hit": 0,
        "form_leak": 0,
        "dup_accession": 0,
        "short": 0,
        "not_preferred": 0,
        "no_anchor": 0,
        "dup_offering": 0,
        "error": 0,
    }

    for start, end in WINDOWS:
        for q in QUERIES:
            if len(docs) >= max_docs:
                break
            try:
                hits = list(search(q, forms="424B5", start=start, end=end, limit=limit_per_query))
            except EdgarError as exc:
                print(f"  ARAMA HATASI {q} {start}: {exc}")
                continue

            for h in hits:
                stats["hit"] += 1
                if len(docs) >= max_docs:
                    break
                if not h.form.upper().startswith("424B"):
                    stats["form_leak"] += 1
                    continue
                if h.accession in seen:
                    stats["dup_accession"] += 1
                    continue
                seen.add(h.accession)

                try:
                    text = strip_html(fetch_document(h))
                except EdgarError:
                    stats["error"] += 1
                    continue

                if len(text) < MIN_SUBSTANTIVE_CHARS:
                    stats["short"] += 1
                    continue
                if not is_preferred_offering(text):
                    stats["not_preferred"] += 1
                    continue

                located = locate_span(text)
                if located is None:
                    stats["no_anchor"] += 1
                    # KAYIP OLCUMU: capa yok ama belge yine de imtiyazli ihrac olabilir mi?
                    m_strong = STRONG_PREF_RE.search(text[:SEARCH_LIMIT])
                    rejects.append(
                        {
                            "accession": h.accession,
                            "company": h.company,
                            "filed_date": h.filed_date,
                            "reason": "no_anchor",
                            "strong_pref_signal": bool(m_strong),
                            "has_liq_pref": bool(LIQ_RE.search(text[:SEARCH_LIMIT])),
                            "snippet": re.sub(
                                r"\s+", " ", text[m_strong.start() - 150 : m_strong.start() + 250]
                            )
                            if m_strong
                            else re.sub(r"\s+", " ", text[:250]),
                        }
                    )
                    continue
                span, offset, anchor = located

                okey = offering_key(h.company, span)
                if okey in seen_offering:
                    stats["dup_offering"] += 1
                    continue
                seen_offering.add(okey)

                docs.append(
                    {
                        "accession": h.accession,
                        "cik": h.cik,
                        "company": h.company,
                        "company_key": h.company.split("  (")[0].strip().lower(),
                        "offering_key": okey,
                        "form": h.form,
                        "filed_date": h.filed_date,
                        "doc_url": h.doc_url,
                        "full_len": len(text),
                        "span_offset": offset,
                        "anchor": anchor,
                        "span": span,
                    }
                )
                print(
                    f"  [{len(docs):>3}] {h.filed_date} {h.company[:36]:36} "
                    f"{len(text):>8,} @{offset:>7,} {okey[-14:]}"
                )

    print("\nSAYIM:")
    for k, v in stats.items():
        print(f"  {k:<14} {v}")
    print(f"  {'TOPLANAN':<14} {len(docs)}")

    if rejects:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with REJECT_FILE.open("w", encoding="utf-8") as fh:
            for r in rejects:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        lost = sum(1 for r in rejects if r["strong_pref_signal"])
        print(f"\nKAYIP OLCUMU ({REJECT_FILE.name}):")
        print(f"  capa bulunamayan            : {len(rejects)}")
        print(f"  ...ama GUCLU imtiyazli sinyal tasiyan: {lost}  <- gercek kayip adayi")
        print(f"  ...sinyal de yok (dogru red): {len(rejects) - lost}")
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=10, help="sorgu+pencere basina sonuc")
    ap.add_argument("--max-docs", type=int, default=200)
    args = ap.parse_args()

    docs = collect(args.per_query, args.max_docs)
    if not docs:
        print("Hicbir belge toplanamadi.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    companies = {d["company_key"] for d in docs}
    offsets = [d["span_offset"] for d in docs]
    late = sum(1 for o in offsets if o > 6_000)
    prelim = sum(1 for d in docs if d["anchor"] == "preliminary")
    print(f"\nYAZILDI: {OUT_FILE} ({len(docs)} belge)")
    print(f"benzersiz sirket : {len(companies)}")
    print(f"benzersiz ihrac  : {len({d['offering_key'] for d in docs})}")
    print(f"span ofseti max  : {max(offsets):,} | medyan {sorted(offsets)[len(offsets)//2]:,}")
    print(f"6.000 sonrasinda baslayan: {late} belge  <- sabit pencere bunlari KACIRIRDI")
    print(f"fiyatlanmis      : {len(docs) - prelim}")
    print(f"on prospektus    : {prelim}  <- kupon null, ABSTENTION dilimi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
