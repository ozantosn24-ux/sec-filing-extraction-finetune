"""Test kumesi insan incelemesi icin tablo + kanit dokumu.

Test kumesi olcumun referansidir: buradaki bir hata tum karsilastirmayi bozar.
Otomatik kontroller gecti ama onlar yalnizca yazildiklari seyi kontrol eder.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "schema" / "TEST_REVIEW.md"


def fmt(v: object) -> str:
    if v is None:
        return "·"
    if isinstance(v, bool):
        return "E" if v else "H"
    if isinstance(v, float):
        return (f"{v:,.4f}".rstrip("0").rstrip(".") if abs(v) < 1 else f"{v:,.2f}".rstrip("0").rstrip("."))
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def main() -> int:
    man = json.loads((INTERIM / "manifest.json").read_text(encoding="utf-8"))
    meta = {m["accession"]: m for m in man["test"]}

    rows = []
    for p in sorted((INTERIM / "labels" / "test").glob("*.json")):
        rows.append((p.stem, json.loads(p.read_text(encoding="utf-8"))))

    # --- Terminal tablosu ---
    hdr = (f"{'#':>2} {'sirket':<26}{'ser':>4}{'kupon':>7}{'liq$':>9}{'birim':>7}"
           f"{'par':>7}{'kum':>4}{'geri':>5}{'sure':>5}{'adet':>13}{'sik':>10}{'on':>3}")
    print(hdr)
    print("-" * len(hdr))
    for i, (acc, d) in enumerate(rows, 1):
        co = meta[acc]["company"].split("  (")[0][:25]
        unit = {"share": "hisse", "depositary_share": "depo", "note": "tahvil"}.get(
            d.get("offered_unit") or "", "·")
        print(
            f"{i:>2} {co:<26}{fmt(d.get('series')):>4}{fmt(d.get('coupon_rate_pct')):>7}"
            f"{fmt(d.get('liquidation_preference_usd')):>9}{unit:>7}"
            f"{fmt(d.get('par_value_usd')):>7}{fmt(d.get('cumulative')):>4}"
            f"{fmt(d.get('redeemable')):>5}{fmt(d.get('perpetual')):>5}"
            f"{fmt(d.get('shares_offered')):>13}"
            f"{(d.get('dividend_frequency') or '·')[:9]:>10}"
            f"{fmt(d.get('is_preliminary')):>3}"
        )

    # --- Kanit dokumu ---
    lines = [
        "# Test kümesi inceleme — 18 kayıt",
        "",
        "Bu kümenin doğruluğu ölçümün referansıdır. Otomatik kontroller geçti ama onlar",
        "yalnızca yazıldıkları şeyi kontrol eder. Aşağıdaki her kaydı ilan metniyle karşılaştır.",
        "",
        "`·` = null (metinde yok). `E`/`H` = evet/hayır.",
        "",
        "**Bakarken şunlara dikkat:** `par` ile `liq$` karışmış mı · `liq$` teklif edilen",
        "birim başına mı (depo yapıda $25, alttaki hisse $25.000 DEĞİL) · `sık` metinde",
        "gerçekten yazıyor mu (varsayılmamış olmalı) · ön prospektüste boş olması gereken",
        "alanlar dolu mu.",
        "",
    ]
    for i, (acc, d) in enumerate(rows, 1):
        m = meta[acc]
        lines += [
            f"## {i}. {m['company']}",
            "",
            f"`{acc}` · {m['filed_date']} · [ilan]({m['doc_url']}) · "
            f"span: `{m['span_file']}`",
            "",
            "| alan | değer | kanıt (metinden birebir) |",
            "|---|---|---|",
        ]
        ev = d.get("evidence") or {}
        for f in ("series", "coupon_rate_pct", "offered_unit", "depositary_ratio",
                  "liquidation_preference_usd", "par_value_usd", "cumulative",
                  "redeemable", "convertible", "perpetual", "shares_offered",
                  "dividend_frequency", "is_preliminary"):
            q = str(ev.get(f, "")).replace("|", "\\|")[:110]
            lines.append(f"| `{f}` | {fmt(d.get(f))} | {q} |")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nKanit dokumu: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
