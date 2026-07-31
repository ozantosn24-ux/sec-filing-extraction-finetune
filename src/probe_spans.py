"""Terimler belgenin NERESINDE? Pencere boyutu tahminle degil OLCUMLE secilir.

Kucuk bir modelin baglamina 395.000 karakter sigmaz. Ama gozlemledigimiz kadariyla
imtiyazli hisse prospektuslerinde tum cekirdek terimler KAPAK sayfasinda toplu.
Bu script bunu dogrular: her belgede anahtar desenlerin ilk gectigi karakter ofseti.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

PATTERNS: dict[str, re.Pattern[str]] = {
    "kupon %": re.compile(r"\b\d{1,2}\.\d{2,3}\s*%", re.I),
    "Series/Class": re.compile(r"\b(?:Series|Class)\s+[A-Z]\b"),
    "Cumulative": re.compile(r"\bCumulative\b", re.I),
    "Liquidation Pref": re.compile(r"Liquidation\s+Preference", re.I),
    "par value $": re.compile(r"par\s+value\s+(?:of\s+)?\$", re.I),
    "Shares (adet)": re.compile(r"\b\d{1,3}(?:,\d{3}){1,3}\s+[Ss]hares\b"),
}


def main() -> int:
    files = sorted(RAW_DIR.glob("*.txt"), key=lambda p: p.stat().st_size)
    if not files:
        print(f"{RAW_DIR} bos — once explore_one.py calistir.")
        return 1

    name_w = 12
    head = f"{'belge':<{name_w}}{'boyut':>9}  " + "  ".join(f"{k:>16}" for k in PATTERNS)
    print(head)
    print("-" * len(head))

    all_last: list[int] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        offsets: list[str] = []
        found_here: list[int] = []
        for pat in PATTERNS.values():
            m = pat.search(text)
            if m:
                offsets.append(f"{m.start():>16,}")
                found_here.append(m.start())
            else:
                offsets.append(f"{'-':>16}")
        print(f"{f.stem[-10:]:<{name_w}}{len(text):>9,}  " + "  ".join(offsets))
        if found_here:
            all_last.append(max(found_here))

    print()
    if all_last:
        worst = max(all_last)
        print(f"En GEC gecen anahtar terim ofseti (tum belgeler): {worst:,}")
        for window in (2000, 4000, 8000, 16000):
            ok = sum(1 for v in all_last if v <= window)
            print(f"  ilk {window:>6,} karakter -> {ok}/{len(all_last)} belgede TUM terimler kapsanir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
