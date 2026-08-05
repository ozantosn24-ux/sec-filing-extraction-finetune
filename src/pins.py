"""Upstream surum sabitleri — TEK KAYNAK.

Guvenlik denetimi 2026-08-05 (C-03): model ve tokenizer `from_pretrained` ile
revision VERILMEDEN aliniyordu. Hugging Face deposu degisirse — ya da hesap ele
gecirilirse — ayni komut BASKA agirliklari indirir ve bu sessizce olur.

Bu, guvenlik sorunundan once bir TEKRAR-URETILEBILIRLIK sorunudur: yayinlanan
%61,1'in arkasindaki agirliklarin hangileri oldugu yaziliysa bir anlami var.
Pinsiz bir kosu "Qwen2.5-1.5B ile olctuk" der ama hangi Qwen2.5-1.5B oldugunu
soyleyemez.

SHA'lar 2026-08-05'te Hugging Face API'sinden cozuldu. Ucu de `safetensors`
yayinliyor, yani pickle deserialization yolu bu modellerde devrede degil.

Yeni pin eklerken SHA'yi EZBERDEN yazma, cozdur:
    curl -s https://huggingface.co/api/models/<repo> \
      | python -c "import sys,json; print(json.load(sys.stdin)['sha'])"
"""

from __future__ import annotations

PINNED_REVISIONS: dict[str, str] = {
    "Qwen/Qwen2.5-1.5B-Instruct": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
    "Qwen/Qwen2.5-3B-Instruct": "aa8e72537993ba99e69dfaafa59ed015b17504d1",
    "HuggingFaceTB/SmolLM2-135M-Instruct": "12fd25f77366fa6b3b4b768ec3050bf629380bac",
}


def revision_for(model_id: str, override: str | None = None) -> str | None:
    """Sabitlenmis revision; yoksa None doner ve SUSMAZ.

    `from_pretrained(..., revision=None)`, revision'i hic vermemekle AYNI sey.
    Yani None donmek davranisi degistirmiyor — degistirdigi tek sey, pinsiz bir
    kosunun artik ekranda gorunur olmasi. Sessiz pinsizlik, bu deponun her yerde
    kacinmaya calistigi seyin ta kendisi.
    """
    if override:
        return override
    rev = PINNED_REVISIONS.get(model_id)
    if rev is None:
        print(
            f"UYARI: '{model_id}' icin sabitlenmis revision YOK -> deponun O ANKI hali\n"
            f"   indirilecek ve kosu tekrar uretilebilir OLMAYACAK.\n"
            f"   Pin listesi: src/pins.py · tek seferlik gecersiz kilma: --revision <sha>"
        )
    return rev
