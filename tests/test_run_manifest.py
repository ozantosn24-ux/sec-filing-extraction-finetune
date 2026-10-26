"""Kosu manifesti kurucusu — CPU'da, sahte girdilerle.

Kurucu torch/peft import etmez; testler de etmez. Gercek bir kosunun manifesti
HENUZ uretilmedi (bkz. `src/run_manifest.py` docstring'i): burada olculen sey
kurucunun sozlesmesidir, gercek bir kosunun icerigi degil.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from run_manifest import (  # noqa: E402
    build_run_manifest,
    canonical_sha256,
    file_sha256,
    write_run_manifest,
)

PEFT = {"r": 16, "lora_alpha": 32, "lora_dropout": 0.05, "bias": "none",
        "task_type": "CAUSAL_LM",
        "target_modules": {"q_proj", "k_proj", "v_proj", "o_proj",
                           "gate_proj", "up_proj", "down_proj"}}
BNB = {"load_in_4bit": True, "bnb_4bit_quant_type": "nf4",
       "bnb_4bit_compute_dtype": "float16", "bnb_4bit_use_double_quant": True}


def kur(**over):
    kw = dict(kind="predict", model_id="Qwen/Qwen2.5-1.5B-Instruct",
              base_revision="a" * 40, tokenizer_revision="a" * 40, dtype="torch.float16",
              bnb_config=BNB, generation_config={"do_sample": False, "max_new_tokens": 160},
              peft_config=PEFT, data_manifest_sha256="d" * 64)
    kw.update(over)
    return build_run_manifest(**kw)


def test_istenen_tum_alanlar_var_ve_json_olur():
    m = kur()
    for k in ("base_revision", "tokenizer_revision", "dtype", "bnb_config",
              "generation_config", "peft_config_sha256", "data_manifest_sha256"):
        assert k in m, k
    assert m["base_revision"] == "a" * 40 and m["dtype"] == "torch.float16"
    assert m["bnb_config"]["bnb_4bit_quant_type"] == "nf4"
    assert m["generation_config"]["do_sample"] is False
    assert m["data_manifest_sha256"] == "d" * 64
    json.dumps(m)  # kume/dtype sizintisi varsa burada patlar


def test_peft_sha_kume_ve_anahtar_sirasindan_bagimsiz():
    a = canonical_sha256(PEFT)
    ters = dict(reversed(list(PEFT.items())))
    ters["target_modules"] = set(reversed(sorted(PEFT["target_modules"])))
    assert canonical_sha256(ters) == a
    assert kur()["peft_config_sha256"] == a


def test_peft_sha_ayar_degisince_DEGISIR():
    # Parmak izi her seye ayni deger donse yukaridaki test de gecerdi.
    assert canonical_sha256({**PEFT, "r": 8}) != canonical_sha256(PEFT)
    assert kur(peft_config={**PEFT, "lora_alpha": 64})["peft_config_sha256"] \
        != kur()["peft_config_sha256"]


def test_pinsiz_kosu_gizlenmez():
    assert kur()["pinned"] is True
    m = kur(base_revision=None)
    assert m["pinned"] is False and m["base_revision"] is None
    assert kur(tokenizer_revision=None)["pinned"] is False


def test_peft_ve_bnb_yoksa_None_uydurma_hash_yok():
    m = kur(peft_config=None, bnb_config=None)
    assert m["peft_config"] is None and m["peft_config_sha256"] is None
    assert m["bnb_config"] is None


def test_gecersiz_kind_reddedilir():
    with pytest.raises(ValueError):
        kur(kind="eval")


def test_file_sha256_yok_dosya_None_var_dosya_hash(tmp_path):
    assert file_sha256(tmp_path / "yok.json") is None
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert file_sha256(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_yazim_diger_kosulari_EZMEZ_ayni_anahtari_gunceller(tmp_path):
    p = tmp_path / "results" / "run_manifest.json"
    write_run_manifest(kur(kind="train"), "train", p)
    write_run_manifest(kur(), "preds_ft_test.jsonl", p)
    write_run_manifest(kur(dtype="torch.float32"), "preds_ft_test.jsonl", p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert set(doc["runs"]) == {"train", "preds_ft_test.jsonl"}
    assert doc["runs"]["preds_ft_test.jsonl"]["dtype"] == "torch.float32"
    assert doc["runs"]["train"]["kind"] == "train"


def _cagri_adlari(dosya: str) -> set[str]:
    return {n.func.id for n in ast.walk(ast.parse((SRC / dosya).read_text(encoding="utf-8")))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


@pytest.mark.parametrize("dosya", ["predict.py", "train_lora.py"])
def test_iki_giris_noktasi_manifesti_GERCEKTEN_yaziyor(dosya):
    """predict/train gercek modeli yukledigi icin CPU'da kosamaz; en azindan
    kurucu ve yazicinin cagrildigini kaynaktan sabitle (cagri silinirse kirmizi)."""
    adlar = _cagri_adlari(dosya)
    assert {"build_run_manifest", "write_run_manifest"} <= adlar, dosya


def test_kurucu_agir_bagimlilik_import_etmez():
    ust = ast.parse((SRC / "run_manifest.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(ust) if isinstance(n, ast.Import)
            for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(ust)
             if isinstance(n, ast.ImportFrom) and n.module}
    assert not mods & {"torch", "transformers", "peft", "trl", "datasets"}
