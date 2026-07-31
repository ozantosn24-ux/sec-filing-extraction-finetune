"""LoRA SFT egitimi — adim ②.

⚠️ API imzalari EZBERDEN yazilmadi: TRL/peft dokumantasyonu 2026-07-31'de canli
dogrulandi (TRL v1.9.2, transformers v5.x). G13'un kurali — "bayat kod parcasi,
olmayan bir hatayi aratmaktan kotudur".

## Dogrulanan ve TUZAK olan uc sey

1. 🔴 **Alan adi `max_length`, `max_seq_length` DEGIL — ve varsayilani 1024.**
   Rehberlerin cogu `max_seq_length=2048` yazar; o ad artik yok, sessizce
   yoksayilir ve 1024'te kalirsin. Bu veri setinde OLCULDU: en uzun dizi 2.626
   token, medyan 2.183. 1024'te ornekLERIN TAMAMI kesilir.
   Ustelik `truncation_mode="keep_start"`, yani kesilen yer kapak sayfasinin
   SONU — cikarilacak alanlar tam orada. Kesilmis ornek metrikte "model
   bulamadi" diye gorunur; oysa metni hic gormemistir.
   ⇒ Bu script `max_length`'i OLCUMDEN alir ve altinda kalirsa DURUR.

2. 🔴 **`bf16` varsayilan olarak True** (fp16 set edilmemisse). Turing'de
   (T4, GTX 16xx — CC 7.5) bf16 YOK. Kopyala-yapistir script tam burada patlar.
   ⇒ Hassasiyet, kartin compute capability'sinden OTOMATIK secilir; tahmin yok.

3. 🔴 **Model string olarak verilirse dtype varsayilani float32.** 1,5B model
   fp32'de ~6 GB agirlik demektir — 16 GB'lik T4'te tek basina yerin ucte ikisi.
   ⇒ `model_init_kwargs={"dtype": ...}` aciktan set ediliyor.

## Veri bicimi

`build_sft.py` her satira hem `messages` hem duz `prompt`/`completion` yaziyor.
Burada **sohbet bicimli prompt-completion** kullaniliyor:
    {"prompt": [{"role":"user",...}], "completion": [{"role":"assistant",...}]}
Sebep: (a) TRL sohbet sablonunu kendisi uygular, yani egitim girdisi CIKARIM
girdisiyle ayni olur; (b) prompt-completion bicimde `completion_only_loss`
varsayilan olarak True — kayip yalniz JSON hedefinde hesaplanir. Duz metin
versiyonunda model 700 token'lik talimati de "uretmeyi" ogrenirdi.

Kullanim:
    python src/train_lora.py --smoke            # CPU'da 2 adim, boru hatti kanit
    python src/train_lora.py                    # gercek kosu (GPU)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
TOKEN_REPORT = PROCESSED / "token_report.json"

# Smoke test icin: kucuk, sohbet sablonu OLAN model. Amac ogrenmek degil,
# borunun ucundan suyun gectigini gormek.
SMOKE_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"


def olculen_max_length() -> int | None:
    """measure_tokens.py'nin raporundaki kesmesiz taban."""
    if not TOKEN_REPORT.exists():
        return None
    return json.loads(TOKEN_REPORT.read_text(encoding="utf-8"))["min_seq_len_no_truncation"]


def hassasiyet_sec(istek: str) -> tuple[bool, bool, str]:
    """(bf16, fp16, gerekce). Karti OLCEREK secer — 'bulutta hallederiz' degil."""
    import torch

    if not torch.cuda.is_available():
        return False, False, "CUDA yok — fp32/CPU"
    major, minor = torch.cuda.get_device_capability()
    ad = torch.cuda.get_device_name()
    ampere = major >= 8
    if istek == "bf16" and not ampere:
        raise SystemExit(
            f"bf16 istendi ama {ad} compute capability {major}.{minor} (Ampere = 8.0+).\n"
            f"Turing'de (T4 dahil) bf16 YOK. --precision fp16 kullanin ya da auto birakin."
        )
    if istek == "fp16":
        return False, True, f"{ad} — fp16 istendi"
    if istek == "bf16":
        return True, False, f"{ad} CC {major}.{minor} — bf16"
    return (True, False, f"{ad} CC {major}.{minor} (Ampere+) — bf16") if ampere else \
           (False, True, f"{ad} CC {major}.{minor} (Turing) — bf16 YOK, fp16'ya dusuldu")


def veri_yukle(split: str, n: int | None = None):
    from datasets import Dataset

    f = PROCESSED / f"sft_{split}.jsonl"
    if not f.exists():
        raise SystemExit(f"{f} yok — once `python src/build_sft.py`")
    rows = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if n:
        rows = rows[:n]
    # YALNIZ iki sutun: TRL bicimi sutunlardan cikariyor, fazlasi belirsizlik yaratir.
    return Dataset.from_list([
        {"prompt": [r["messages"][0]], "completion": [r["messages"][1]]} for r in rows
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "lora-qwen2.5-1.5b")
    ap.add_argument("--max-length", type=int, default=3072)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=1e-4,
                    help="adaptor egitiminde ~1e-4; SFTConfig varsayilani 2e-5 TAM MODEL icin")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--precision", choices=("auto", "bf16", "fp16"), default="auto")
    ap.add_argument("--4bit", dest="four_bit", action="store_true",
                    help="QLoRA: taban modeli NF4 4-bit yukle (dar VRAM icin)")
    ap.add_argument("--smoke", action="store_true",
                    help="kucuk model + 2 adim: ogrenme degil, BORU HATTI dogrulamasi")
    args = ap.parse_args()

    import torch
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    model_id = SMOKE_MODEL if args.smoke else args.model
    olculen = olculen_max_length()

    # 🔴 Kesme sessiz bir veri kaybidir: once DURDUR, sonra egit.
    if olculen and args.max_length < olculen and not args.smoke:
        raise SystemExit(
            f"max_length={args.max_length} < olculen taban {olculen}.\n"
            f"Bu ayarla ornekler KESILIR ve kesilen yer kapak sayfasinin sonudur "
            f"(truncation_mode='keep_start'), yani cikarilacak alanlar.\n"
            f"`python src/measure_tokens.py` raporuna bakin veya --max-length {olculen} verin."
        )

    bf16, fp16, gerekce = hassasiyet_sec(args.precision)
    dtype = torch.bfloat16 if bf16 else (torch.float16 if fp16 else torch.float32)
    print(f"model      : {model_id}{'   [SMOKE]' if args.smoke else ''}")
    print(f"hassasiyet : {gerekce}")
    print(f"max_length : {args.max_length}" + (f"  (olculen taban {olculen})" if olculen else ""))

    train = veri_yukle("train", n=4 if args.smoke else None)
    print(f"egitim ornegi: {len(train)}")

    quant = None
    if args.four_bit:
        from transformers import BitsAndBytesConfig
        quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                   bnb_4bit_compute_dtype=dtype,
                                   bnb_4bit_use_double_quant=True)

    cfg = SFTConfig(
        output_dir=str(args.out),
        # 🔴 `max_length` — `max_seq_length` DEGIL. Varsayilani 1024.
        max_length=args.max_length,
        num_train_epochs=2 if args.smoke else args.epochs,
        max_steps=2 if args.smoke else -1,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=1 if args.smoke else args.grad_accum,
        learning_rate=args.lr,
        bf16=bf16,
        fp16=fp16,
        # Model string olarak veriliyor -> dtype AKTARILMAZSA fp32 olur.
        model_init_kwargs={"dtype": dtype},
        # prompt-completion veri setinde varsayilani zaten True; ACIKTAN yaziliyor
        # cunku bu, egitimin ne ogrendigini belirleyen tek satir: kayip yalniz
        # JSON hedefinde, 700 token'lik talimatta DEGIL.
        completion_only_loss=True,
        packing=False,  # paketleme ornekleri birbirine karistirir; burada her belge ayri
        logging_steps=1 if args.smoke else 5,
        save_strategy="no" if args.smoke else "epoch",
        report_to=[],
        seed=42,
        use_cpu=args.smoke and not torch.cuda.is_available(),
    )

    peft_cfg = LoraConfig(
        r=args.rank,
        lora_alpha=args.rank * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        # Dikkat/MLP projeksiyonlari. "all-linear" da gecerli bir secim; sabit
        # liste yazildi ki kosu tekrar-uretilebilir olsun.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )

    trainer = SFTTrainer(
        model=model_id,
        args=cfg,
        train_dataset=train,
        peft_config=peft_cfg,
        quantization_config=quant,
    )

    # Kayip maskesi GERCEKTEN dogru mu? Sayilara degil ICERIGE bak: ilk ornegin
    # etiketlerinde -100 OLMAYAN kisim, yalniz JSON hedefi olmali. Bu kontrol
    # olmadan "egitim kostu" ile "dogru sey ogrendi" ayirt edilemez.
    ornek = trainer.train_dataset[0]
    if "labels" in ornek:
        etiketli = sum(1 for x in ornek["labels"] if x != -100)
        toplam = len(ornek["labels"])
        print(f"kayip maskesi: {toplam} token'in {etiketli}'sinde kayip hesaplaniyor "
              f"(%{100*etiketli/toplam:.1f})")
        if etiketli > toplam * 0.5:
            print("  ⚠️ token'larin YARISINDAN fazlasinda kayip var — completion_only "
                  "maskesi beklendigi gibi calismiyor olabilir, kontrol edin")

    trainer.train()

    if not args.smoke:
        trainer.save_model(str(args.out))
        print(f"\nadaptor -> {args.out}")
    if torch.cuda.is_available():
        print(f"tepe VRAM: {torch.cuda.max_memory_allocated()/2**30:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
