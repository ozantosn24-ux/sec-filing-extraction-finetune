"""Model ciktisi uretimi — egitilmis adaptor ya da duz prompted model.

`evaluate.py`'nin bekledigi bicimde yazar: her satirda modelin HAM metni.
Ayristirilmis sozluk yazsaydik "gecersiz JSON uretti" vakasi olcum defterinden
duserdi — sema gecerliligi bir METRIK, ciktinin on-islenmesi degil.

Ayni script iki yarismaciyi da kosar:
    --adapter models/lora-...     -> fine-tuned kucuk model
    (adaptor vermeden)            -> ayni modelin PROMPTED hali (adaptorun
                                     gercekten fark yaratip yaratmadigi ancak
                                     bu ikisi karsilastirilinca bilinir)

Uretim GREEDY (do_sample=False): olcum tekrar-uretilebilir olmali, ayni girdi
ayni ciktiyi vermeli. Ornekleme, skoru kosudan kosuya oynatirdi.

Kullanim:
    python src/predict.py --adapter models/lora-qwen2.5-1.5b -o preds_ft.jsonl
    python src/predict.py --limit 3 --model HuggingFaceTB/SmolLM2-135M-Instruct  # smoke
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"

# Hedef JSON olculdu: medyan 92, en uzun 102 token. 160 rahat pay birakir;
# daha da buyutmek yalnizca bozuk ciktida bos yere beklemek olurdu.
MAX_NEW_TOKENS = 160


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--adapter", type=Path, help="LoRA adaptor dizini (yoksa duz prompted)")
    ap.add_argument("--split", default="test", choices=("train", "test"))
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--limit", type=int, help="yalniz ilk N kayit (smoke test)")
    ap.add_argument("--max-new-tokens", type=int, default=MAX_NEW_TOKENS)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    f = PROCESSED / f"sft_{args.split}.jsonl"
    if not f.exists():
        raise SystemExit(f"{f} yok — once `python src/build_sft.py`")
    rows = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if args.limit:
        rows = rows[:args.limit]

    cuda = torch.cuda.is_available()
    dtype = torch.float32
    if cuda:
        dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16

    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=dtype,
                                                 device_map="auto" if cuda else None)
    etiket = args.model
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(args.adapter))
        etiket = f"{args.model}+{args.adapter.name}"
    model.eval()
    print(f"model: {etiket}  | dtype {dtype} | {'cuda' if cuda else 'cpu'} | {len(rows)} kayit")

    out = (args.out or PROCESSED /
           f"preds_{'ft' if args.adapter else 'prompted'}_{args.split}.jsonl").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for i, r in enumerate(rows, 1):
            # Egitimdeki ile AYNI sablon: sadece kullanici mesaji + uretim capasi.
            text = tok.apply_chat_template([r["messages"][0]], tokenize=False,
                                           add_generation_prompt=True)
            enc = tok(text, return_tensors="pt").to(model.device)
            t0 = time.perf_counter()
            with torch.no_grad():
                gen = model.generate(**enc, max_new_tokens=args.max_new_tokens,
                                     do_sample=False, pad_token_id=tok.pad_token_id or tok.eos_token_id)
            dt = time.perf_counter() - t0
            # YALNIZ yeni token'lar; prompt'u geri yazmak ciktiyi kirletirdi.
            raw = tok.decode(gen[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
            fh.write(json.dumps({"accession": r["accession"], "raw": raw,
                                 "latency_s": round(dt, 3), "model": etiket},
                                ensure_ascii=False) + "\n")
            if i % 10 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}  son gecikme {dt:.2f}s")

    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
