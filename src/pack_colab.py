"""Colab paketi — yuklenecek TEK dosyayi uretir.

COLAB.md alti ayri dosya yuklemeyi anlatiyor ve bu, elle yapildiginda en sik
atlanan sey `token_export`... daha dogrusu `token_report.json` oluyor (olculdu:
izole denemede eksikti ve kesme korumasi sessizce kapaliydi). Tek zip = atlanacak
dosya yok.

Script dosyalarin VARLIGINI dogrular ve eksik varsa PAKETLEMEZ — yarim bir paketi
Colab'de fark etmek, oturumu bosa harcamak demek.

Kullanim:
    python src/pack_colab.py
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "colab-bundle.zip"

# Izole bir dizinde DOGRULANDI (2026-08-01): yalniz bu dosyalarla smoke test ve
# predict.py kosuyor. Fazlasi gereksiz, eksigi sessiz ariza.
DOSYALAR = [
    "src/prompt.py",
    "src/train_lora.py",
    "src/predict.py",
    "data/processed/sft_train.jsonl",
    "data/processed/sft_dev.jsonl",
    "data/processed/sft_test.jsonl",
    # Kesme korumasi olculen tabani BURADAN okuyor; yoksa koruma kapali kalir.
    "data/processed/token_report.json",
]


def main() -> int:
    eksik = [d for d in DOSYALAR if not (ROOT / d).exists()]
    if eksik:
        raise SystemExit(
            "PAKETLENMEDI — eksik dosya:\n" + "\n".join(f"  {d}" for d in eksik)
            + "\n\nOnce sirasiyla: python src/build_sft.py && python src/measure_tokens.py"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for d in DOSYALAR:
            z.write(ROOT / d, d)

    rapor = json.loads((ROOT / "data" / "processed" / "token_report.json").read_text(encoding="utf-8"))
    print(f"paket: {OUT}")
    print(f"boyut: {OUT.stat().st_size/2**20:.1f} MB  ({len(DOSYALAR)} dosya)")
    print(f"\niceridekiler:")
    for d in DOSYALAR:
        print(f"   {d}  ({(ROOT/d).stat().st_size/1024:>8,.0f} KB)")
    print(f"\nolculen taban seq_len : {rapor['min_seq_len_no_truncation']} "
          f"-> onerilen {rapor['recommended_seq_len']}")
    print("Colab: colab/edgar_finetune.ipynb not defterini acin, 3. hucreye bu zip'i yukleyin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
