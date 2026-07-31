"""TEK bir gercek dosyalamayi indirip ICERIGINE bak.

Sema tasarimindan ONCE calisir. Kural: toplu kosudan once tek kayitta ciktinin
icerigine bakilir — dolu dosya/200 yanit dogruluk kaniti degildir.
"""

from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edgar import fetch_document, search  # noqa: E402

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    # Elle entity listesi EKSIK kaliyordu (&#147; &#146; &#160; gecti) — stdlib kullan.
    text = _html.unescape(text)
    # OLCULDU: SEC belgelerinde Unicode bosluklar bol — U+2003 em-space 524x,
    # U+2007 figure-space 353x, U+2009 thin-space 45x, U+200A 26x, U+2002 16x.
    # `[ \t\xa0]+` bunlari KACIRIYORDU: 'par value' aramasi 0 eslesme donuyor,
    # metinde acikca yazmasina ragmen. Kural-tabanli baseline'i sessizce sakat
    # birakir -> fine-tuned model haksiz yere "kazanir", karsilastirma yalan olur.
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else '"Cumulative Redeemable Preferred"'
    start = sys.argv[2] if len(sys.argv) > 2 else "2025-01-01"
    end = sys.argv[3] if len(sys.argv) > 3 else "2026-07-31"
    print(f"ARAMA: q={query} forms=424B5 {start}..{end}")

    hits = list(search(query, forms="424B5", start=start, end=end, limit=10))
    if not hits:
        print("Sonuc yok.")
        return 1

    print(f"\n{len(hits)} ham sonuc:")
    for i, h in enumerate(hits):
        print(f"  [{i}] {h.filed_date} | {h.form:14} | {h.company[:42]:42} | {h.primary_doc}")

    # OLCULDU: forms=424B5 filtresi SIZDIRIYOR (EX-FILING FEES donuyor) -> elde dogrula.
    real = [h for h in hits if h.form.upper().startswith("424B")]
    dropped = len(hits) - len(real)
    if dropped:
        print(f"\n  -> {dropped} sonuc form filtresi sizdirdigi icin ELENDI")
    if not real:
        print("424B belgesi yok.")
        return 1

    # OLCULDU: 424B5 kutusunda ASIL prospektus ile kisa tadil belgeleri karisik.
    # Uzunluk ayirt edici -> adaylari indir, olc, en uzununu incele.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n{len(real)} aday indiriliyor ve OLCULUYOR:")
    scored: list[tuple[int, object, str]] = []
    for h in real:
        try:
            raw = fetch_document(h)
        except Exception as exc:  # noqa: BLE001
            print(f"  ATLANDI {h.accession}: {exc}")
            continue
        body = strip_html(raw)
        scored.append((len(body), h, body))
        (RAW_DIR / f"{h.accession}.txt").write_text(body, encoding="utf-8")
        kind = "ASIL prospektus" if len(body) > 20000 else "kisa tadil/ek"
        print(f"  {len(body):>8,} karakter | {h.filed_date} | {h.company[:34]:34} | {kind}")

    if not scored:
        print("Hicbir belge indirilemedi.")
        return 1

    scored.sort(key=lambda t: -t[0])
    _, target, text = scored[0]
    print(f"\nEN UZUN SECILDI: {target.company} — {target.doc_url}")
    print("\n" + "=" * 70)
    print("ILK 3000 KARAKTER (gercek icerik — sema bundan turetilecek)")
    print("=" * 70)
    print(text[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
