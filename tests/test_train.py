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
