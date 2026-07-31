"""Token uzunlugu OLCUMU — tahmin degil.

`seq_len` kararini bu belirler, `seq_len` de VRAM'i, VRAM de hangi GPU'nun gercekten
gerektigini. "6.000 karakter ~ 1.500 token" gibi bir kestirim burada yeterli DEGIL:
kesme (truncation) sessizce kapak sayfasinin sonunu atar ve tam da cikarilacak
alanlar orada olabilir. Kesilen ornek, "model bulamadi" diye gorunur — oysa
metni hic gormemistir.

Chat sablonu ONEMLI: sablonun kendisi token ekler ve egitim girdisi sablonlanmis
halidir. Ham metni olcup sablonlu egitmek, tam kapasitede sessiz kesme demektir.
Bu yuzden ikisi de olculuyor.

Kullanim:
    python src/measure_tokens.py [--model Qwen/Qwen2.5-1.5B-Instruct]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
REPORT = PROCESSED / "token_report.json"

# Aday pencereler. Truncation sayisi her biri icin ayri raporlanir ki secim
# "kac ornegi feda ediyorum" sorusuna bakarak yapilsin.
CANDIDATES = [1024, 1536, 2048, 3072, 4096]


def pct(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    i = min(len(sorted_vals) - 1, int(round((len(sorted_vals) - 1) * p)))
    return sorted_vals[i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model)
    print(f"tokenizer: {args.model}  ({tok.__class__.__name__})\n")

    from prompt import INSTRUCTION

    instr_tokens = len(tok(INSTRUCTION, add_special_tokens=False)["input_ids"])
    print(f"TALIMATIN KENDISI: {instr_tokens} token — her ornekte tekrar eder, "
          f"sabit maliyet\n")

    out: dict = {"model": args.model, "instruction_tokens": instr_tokens, "splits": {}}

    for split in ("train", "dev", "test"):
        f = PROCESSED / f"sft_{split}.jsonl"
        if not f.exists():
            # dev istege bagli (`build_sft.py --no-dev`); train/test zorunlu.
            if split == "dev":
                continue
            raise SystemExit(f"{f} yok — once `python src/build_sft.py`")
        rows = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]

        raw, templated, comp = [], [], []
        for r in rows:
            raw.append(len(tok(r["prompt"], add_special_tokens=False)["input_ids"]))
            comp.append(len(tok(r["completion"], add_special_tokens=False)["input_ids"]))
            # Egitimde gercekten verilecek dizi: sablonlanmis tam sohbet.
            text = tok.apply_chat_template(r["messages"], tokenize=False)
            templated.append(len(tok(text, add_special_tokens=False)["input_ids"]))

        raw.sort(); templated.sort(); comp.sort()
        print(f"--- {split} (n={len(rows)}) ---")
        print(f"  prompt (ham)      med={pct(raw,.5):>5}  p95={pct(raw,.95):>5}  max={raw[-1]:>5}")
        print(f"  TAM dizi (sablon) med={pct(templated,.5):>5}  p95={pct(templated,.95):>5}  max={templated[-1]:>5}")
        print(f"  hedef JSON        med={pct(comp,.5):>5}  p95={pct(comp,.95):>5}  max={comp[-1]:>5}")
        print("  seq_len adaylari (sablonlu tam diziye gore):")
        for c in CANDIDATES:
            lost = sum(1 for t in templated if t > c)
            mark = "  <- hepsi siger" if lost == 0 else ""
            print(f"     {c:>5}: {lost:>3}/{len(templated)} ornek KESILIR{mark}")

        out["splits"][split] = {
            "n": len(rows),
            "prompt_raw": {"med": pct(raw, .5), "p95": pct(raw, .95), "max": raw[-1]},
            "full_templated": {"med": pct(templated, .5), "p95": pct(templated, .95),
                               "max": templated[-1]},
            "completion": {"med": pct(comp, .5), "p95": pct(comp, .95), "max": comp[-1]},
            "truncated_at": {str(c): sum(1 for t in templated if t > c) for c in CANDIDATES},
            "total_tokens": sum(templated),
        }
        print()

    both = out["splits"]
    need = max(both["train"]["full_templated"]["max"], both["test"]["full_templated"]["max"])
    fits = next((c for c in CANDIDATES if c >= need), None)
    out["min_seq_len_no_truncation"] = need
    out["recommended_seq_len"] = fits

    print(f"KESMESIZ GEREKEN dizi uzunlugu : {need}")
    print(f"ONERILEN seq_len               : {fits}"
          f"{' (aday listesinde yok — pencereyi buyut)' if fits is None else ''}")
    print(f"Egitim seti toplam token       : {both['train']['total_tokens']:,}")
    print("\nNOT: bu sayilar VRAM'i TEK BASINA belirlemez — batch, gradient "
          "checkpointing ve LoRA rank da girer. Belirledigi sey, kesme olmadan "
          "egitmek icin gereken TABAN.")

    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rapor -> {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
