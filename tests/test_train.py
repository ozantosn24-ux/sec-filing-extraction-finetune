"""Egitim scriptinin KARAR verdigi yerlerin testleri.

Egitimin kendisi test edilmiyor (GPU ister); test edilen sey, para ve saat
yakan kararlar: hassasiyet secimi ve dizi uzunlugu. Ikisi de sessizce yanlis
olabilecek turden — biri kosuyu patlatir, digeri patlatmaz ama veriyi keser.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import train_lora  # noqa: E402


class SahteCuda:
    """torch.cuda yerine gecen asgari cift."""

    def __init__(self, capability, ad="Sahte GPU"):
        self._cap, self._ad = capability, ad

    def is_available(self):
        return self._cap is not None

    def get_device_capability(self):
        return self._cap

    def get_device_name(self):
        return self._ad


@pytest.fixture
def gpu(monkeypatch):
    import torch

    def kur(capability, ad="Sahte GPU"):
        monkeypatch.setattr(torch, "cuda", SahteCuda(capability, ad))

    return kur


# --- hassasiyet: G13'un en pahali dersi --------------------------------------


def test_TURING_bf16_ISTEGI_REDDEDILIR(gpu):
    """🔴 T4 de Turing. "Buluta cikinca hallederiz" bf16 icin GECERSIZ.

    Sessizce fp16'ya dusmek DE yanlis olurdu: kullanici bf16 istedigini sanip
    farkli bir sayisal rejimde egitirdi. Aciktan durur ve neden oldugunu soyler.
    """
    gpu((7, 5), "Tesla T4")
    with pytest.raises(SystemExit) as exc:
        train_lora.hassasiyet_sec("bf16")
    assert "Turing" in str(exc.value)


def test_AUTO_turingde_fp16_secer(gpu):
    gpu((7, 5), "NVIDIA GeForce GTX 1650 SUPER")
    bf16, fp16, gerekce = train_lora.hassasiyet_sec("auto")
    assert (bf16, fp16) == (False, True)
    assert "Turing" in gerekce


def test_AUTO_amperede_bf16_secer(gpu):
    gpu((8, 6), "NVIDIA RTX A5000")
    bf16, fp16, _ = train_lora.hassasiyet_sec("auto")
    assert (bf16, fp16) == (True, False)


def test_AUTO_hopperda_da_bf16(gpu):
    """Kural "== 8" degil ">= 8" olmali; yoksa daha yeni kartlar fp16'ya duser."""
    gpu((9, 0), "NVIDIA H100")
    assert train_lora.hassasiyet_sec("auto")[0] is True


def test_CUDA_yoksa_ikisi_de_KAPALI(gpu):
    gpu(None)
    assert train_lora.hassasiyet_sec("auto") == (False, False, "CUDA yok — fp32/CPU")


# --- CPU korumasi: makineyi kullanilamaz hale getiren kosu -------------------


def test_CPU_buyuk_model_DURDURULUR(gpu, monkeypatch):
    """CUDA yok + 1,5B model = fp32'de ~6 GB agirlik, 16 GB makinede takas.
    Olculdu: 135M bu CPU'da 32 sn/adim; 1,5B gun mertebesi. Kosmamali."""
    gpu(None)
    monkeypatch.setattr(train_lora, "parametre_sayisi", lambda m: 1_543_714_304)
    with pytest.raises(SystemExit) as exc:
        train_lora.cpu_korumasi("Qwen/Qwen2.5-1.5B-Instruct", force=False, smoke=False)
    assert "DURDURULDU" in str(exc.value)
    assert "COLAB.md" in str(exc.value)  # ne yapacagini soylemeden durdurma


def test_CPU_kucuk_model_GECER(gpu, monkeypatch):
    """Sinirin altindaki model CPU'da kosabilmeli; koruma her seyi engellemez."""
    gpu(None)
    monkeypatch.setattr(train_lora, "parametre_sayisi", lambda m: 135_000_000)
    train_lora.cpu_korumasi("kucuk", force=False, smoke=False)  # exception YOK


def test_smoke_korumadan_MUAF(gpu, monkeypatch):
    """--smoke bilerek CPU'da kosar; boru hattini pod acmadan once kanitlar."""
    gpu(None)
    monkeypatch.setattr(train_lora, "parametre_sayisi", lambda m: 7_000_000_000)
    train_lora.cpu_korumasi("dev-model", force=False, smoke=True)


def test_force_cpu_gecer_ama_UYARIR(gpu, monkeypatch, capsys):
    gpu(None)
    monkeypatch.setattr(train_lora, "parametre_sayisi", lambda m: 1_543_714_304)
    train_lora.cpu_korumasi("buyuk", force=True, smoke=False)
    assert "yavaslar" in capsys.readouterr().out


def test_GPU_varsa_koruma_KARISMAZ(gpu, monkeypatch):
    gpu((7, 5), "Tesla T4")
    monkeypatch.setattr(train_lora, "parametre_sayisi",
                        lambda m: pytest.fail("GPU varken boyut sorulmamali"))
    train_lora.cpu_korumasi("Qwen/Qwen2.5-1.5B-Instruct", force=False, smoke=False)


def test_boyut_DOGRULANAMAZSA_durur(gpu, monkeypatch):
    """Ag yoksa "bilmiyorum" sessizce "devam et"e cevrilmemeli."""
    gpu(None)
    monkeypatch.setattr(train_lora, "parametre_sayisi", lambda m: None)
    with pytest.raises(SystemExit) as exc:
        train_lora.cpu_korumasi("bilinmeyen", force=False, smoke=False)
    assert "DOGRULANAMADI" in str(exc.value)


# --- dizi uzunlugu: sessiz veri kaybi ----------------------------------------


def test_olculen_taban_RAPORDAN_okunur(tmp_path, monkeypatch):
    """seq_len tahmin edilmez; measure_tokens.py'nin olctugu sayidan gelir."""
    rapor = tmp_path / "token_report.json"
    rapor.write_text(json.dumps({"min_seq_len_no_truncation": 2626}), encoding="utf-8")
    monkeypatch.setattr(train_lora, "TOKEN_REPORT", rapor)
    assert train_lora.olculen_max_length() == 2626


def test_rapor_yoksa_None(tmp_path, monkeypatch):
    monkeypatch.setattr(train_lora, "TOKEN_REPORT", tmp_path / "yok.json")
    assert train_lora.olculen_max_length() is None


# --- veri bicimi: TRL'in kaybi nerede hesapladigini bu belirler ---------------


def test_veri_sohbet_bicimli_prompt_completion():
    """TRL bicimi SUTUNLARDAN cikariyor. Fazla sutun birakmak belirsizlik olurdu;
    `prompt`/`completion` cifti ise `completion_only_loss`'u varsayilan yapar.

    Veri uretilmemisse ATLANIR — `veri_yukle` uretim yolunda bilerek SystemExit
    atiyor (egitim, eksik veriyle sessizce baslamamali), ama testin bunu bir
    BASARISIZLIK gibi gostermesi yanlis: depoyu klonlayan biri kirmizi bir test
    gorurdu. test_sft.py'daki veri testleriyle ayni davranis.
    """
    if not (train_lora.PROCESSED / "sft_test.jsonl").exists():
        pytest.skip("data/processed/sft_test.jsonl yok — once `python src/build_sft.py`")
    ds = train_lora.veri_yukle("test", n=2)
    assert set(ds.column_names) == {"prompt", "completion"}
    ornek = ds[0]
    assert ornek["prompt"][0]["role"] == "user"
    assert ornek["completion"][0]["role"] == "assistant"
    # Hedef gercekten JSON, serbest metin degil
    assert json.loads(ornek["completion"][0]["content"])


# --- 4-bit: yalniz Colab'de kosar, ama BURADA test edilebilir ----------------


def test_4bit_kapaliyken_None():
    assert train_lora.quant_config(False, None) is None


def test_4bit_NF4_ve_cift_kuantizasyon():
    import torch

    c = train_lora.quant_config(True, torch.float16)
    assert c.load_in_4bit is True
    assert c.bnb_4bit_quant_type == "nf4"
    assert c.bnb_4bit_use_double_quant is True


def test_4bit_compute_dtype_HASSASIYETI_izler():
    """T4'te fp16 secilip compute_dtype bf16 kalsaydi hata YALNIZ Colab'de
    ortaya cikardi. Egitim ve uretim ayni fonksiyondan aliyor."""
    import torch

    assert train_lora.quant_config(True, torch.float16).bnb_4bit_compute_dtype == torch.float16
    assert train_lora.quant_config(True, torch.bfloat16).bnb_4bit_compute_dtype == torch.bfloat16


# --- VRAM probu: tepe, EN UZUN dizide olusur ---------------------------------


class SahteTokenizer:
    """Token sayisi = karakter sayisi. Amac siralamayi test etmek, tokenizer'i degil."""

    def apply_chat_template(self, messages, tokenize=False):
        return "".join(m["content"] for m in messages)

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": list(range(len(text)))}


@pytest.fixture
def sahte_tokenizer(monkeypatch):
    import transformers

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained",
                        classmethod(lambda cls, *a, **k: SahteTokenizer()))


def _satir(acc: str, uzunluk: int) -> dict:
    return {"accession": acc,
            "messages": [{"role": "user", "content": "x" * uzunluk},
                         {"role": "assistant", "content": ""}]}


def test_prob_EN_UZUN_diziyi_basa_alir(sahte_tokenizer):
    """🔴 Tepe VRAM en uzun diziyle olusur. Kayitlar accession'a gore sirali,
    yani ilk adimlar rastgele uzunlukta: prob GECER, gercek kosu ilerideki
    uzun ornekte OOM verir — kiralik saatin ortasinda.
    """
    rows = [_satir("a", 100), _satir("b", 900), _satir("c", 400)]
    assert [r["accession"] for r in train_lora.en_uzun_once(rows, "sahte")] == ["b", "c", "a"]


def test_prob_sirasi_dosya_sirasindan_FARKLI(sahte_tokenizer):
    """Siralama gercekten bir sey degistiriyor mu? Degistirmiyorsa prob, eski
    `--epochs 0.05` yaklasimindan farksizdir ve fazladan guven verir."""
    rows = [_satir("a", 100), _satir("b", 900), _satir("c", 400)]
    assert [r["accession"] for r in train_lora.en_uzun_once(rows, "sahte")] \
        != [r["accession"] for r in rows]


def test_ham_satirlar_veri_yoksa_DURUR(monkeypatch, tmp_path):
    """Eksik veriyle egitim sessizce baslamamali."""
    monkeypatch.setattr(train_lora, "PROCESSED", tmp_path)
    with pytest.raises(SystemExit) as exc:
        train_lora.ham_satirlar("train")
    assert "build_sft" in str(exc.value)


def test_rapor_yoksa_kesme_korumasi_SESSIZ_KALMAZ(tmp_path, monkeypatch, capsys):
    """token_report.json yoksa `max_length` kontrolu devre disi kalir — ve bu,
    korumanin EN COK gerektigi yerde (Colab) tam olarak boyleydi.

    Olculdu: izole bir dizinde, rapor olmadan `--max-length 2048` engellenmedi.
    Runbook'un dosya listesi eksikti. Duzeltme iki tarafli: liste duzeltildi ve
    script artik susmak yerine aciktan uyariyor.
    """
    monkeypatch.setattr(train_lora, "TOKEN_REPORT", tmp_path / "yok.json")
    assert train_lora.olculen_max_length() is None
