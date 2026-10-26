"""Dondurulmus skorlama hatti, CPU'da, her push'ta: kural-tabanli baseline'i test
bolmesinin etiketleri uzerinde YENIDEN kosturur ve commit'li `baseline_metrics.json` ile
karsilastirir.

Bu yeni bir OLCUM degil: kural-tabanli cikarici deterministik (model, GPU, ag yok) ve
sayilari README'de zaten yayinli. Test, yayinli sayinin hala uretilebildigini korur —
`extract_rules.py`, `evaluate.py`, `prompt.normalize_span` ya da etiketler sessizce
degisirse kirmizi olur. Fine-tuned model GPU ister; onun icin bu test bir sey SOYLEMEZ.

ESIK: BIREBIR ESITLIK, tolerans yok. Girdi (span + altin etiket) git'te sabit, kod
deterministik, karsilastirilan sey tam sayilar (kayit/alan sayilari). Tolerans, "yayinli
27.8%'in 1 kayit altina dusmesi" gibi gercek bir gerilemeyi ortadan kaldirirdi; n=36'da
bir kayit 2.8 puandir. Gecikme (duvar saati) bilerek DAHIL DEGIL — tek kararsiz alan.
Sayi bilerek degisecekse JSON elle yenilenir:

    python tests/test_baseline_metrics.py --write

ve fark commit'te gorunur. Bu bayrak testin KENDI parcasi degildir; pytest asla yazmaz.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from evaluate import FIELD_ORDER, load_gold, score  # noqa: E402
from extract_rules import SPAN_DIR, extract  # noqa: E402

BASELINE = Path(__file__).resolve().parent / "baseline_metrics.json"

# README sonuc tablosundaki kural-tabanli sutun (BAGIMSIZ capa): JSON yanlislikla
# kirli bir koddan yeniden uretilse bile bu sayilar yayinli olandan sapmayi yakalar.
README_ANCHOR = {"kayit": 36, "sema_gecerli": 36, "tam_kayit": 10,
                 "abstention": [111, 123], "uydurma": [12, 123], "zor_vaka": [31, 38]}


def olc() -> dict:
    gold = load_gold("test")
    rows = []
    for p in sorted((SPAN_DIR / "test").glob("*.txt")):
        obj = extract(p.read_text(encoding="utf-8"))
        rows.append({"accession": p.stem,
                     "raw": json.dumps({f: obj[f] for f in FIELD_ORDER}, ensure_ascii=False)})
    s = score(rows, gold)
    return {
        "split": "test",
        "kayit": s["kayit"],
        "sema_gecerli": s["sema_gecerli"],
        "tam_kayit": s["tam_kayit"],
        "abstention": list(s["abstention"]),
        "uydurma": list(s["uydurma"]),
        "kacirma": list(s["kacirma"]),
        "zor_vaka": list(s["zor_vaka"]),
        "unit_vakasi": s["unit_vakasi"],
        "alan": {f: list(v) for f, v in s["alan"].items()},
    }


def test_baseline_commitli_json_ile_BIREBIR_esit():
    beklenen = json.loads(BASELINE.read_text(encoding="utf-8"))
    simdi = olc()
    assert simdi == beklenen, (
        "kural-tabanli baseline sayilari commit'li baseline_metrics.json'dan saptı.\n"
        f"  commit'li: {json.dumps(beklenen, sort_keys=True)}\n"
        f"  simdi    : {json.dumps(simdi, sort_keys=True)}\n"
        "Degisiklik BILEREK ise: python tests/test_baseline_metrics.py --write ve farki commit'le."
    )


def test_baseline_JSON_README_yayinli_sayilarla_ESLESIR():
    """Yalniz JSON'u JSON'la karsilastiran test, yanlis yenilenmis dosyayi kabul ederdi."""
    b = json.loads(BASELINE.read_text(encoding="utf-8"))
    for k, v in README_ANCHOR.items():
        assert b[k] == v, f"{k}: commit'li JSON {b[k]!r}, README'de yayinli {v!r}"


def test_baseline_vakumda_gecmez():
    """Bos test bolmesi ya da bos tahmin 'esit' sayilirdi."""
    assert len(load_gold("test")) == 36
    assert len(list((SPAN_DIR / "test").glob("*.txt"))) == 36
    assert olc()["kayit"] == 36


if __name__ == "__main__":
    if "--write" not in sys.argv:
        raise SystemExit("kullanim: python tests/test_baseline_metrics.py --write")
    BASELINE.write_text(json.dumps(olc(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"-> {BASELINE}")
