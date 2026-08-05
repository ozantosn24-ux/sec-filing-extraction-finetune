"""Upstream pin'leri — sabit gercekten sabit mi, ve geri kayiyor mu?

Guvenlik denetimi 2026-08-05 (C-03): model/tokenizer revision'siz aliniyordu ve
not defteri degisebilir `main`'i klonluyordu. Buradaki testler o yuzeyin sessizce
eski haline donmesini yakalamak icin var — asil deger tek bir kosuda degil,
ilerideki bir commit'in pini kaldirdiginda kirmizi yanmasinda.

Ag YOK: SHA'larin Hugging Face'te GERCEKTEN durup durmadigi burada dogrulanmaz
(CI'i disariya bagimli yapardi). Burada dogrulanan, pinin VAR ve tutarli olmasi.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pins import PINNED_REVISIONS, revision_for  # noqa: E402

SHA_RE = re.compile(r"[0-9a-f]{40}")
NOTEBOOK = ROOT / "colab" / "edgar_finetune.ipynb"


def _notebook_source() -> str:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "\n".join("".join(c.get("source", [])) for c in nb["cells"])


# --- pins modulu --------------------------------------------------------------


def test_pinler_TAM_SHA_yoksa_pin_degil():
    """Etiket ya da dal adi pin sayilmaz — ikisi de oynatilabilir."""
    assert PINNED_REVISIONS, "pin listesi bos"
    for model_id, rev in PINNED_REVISIONS.items():
        assert SHA_RE.fullmatch(rev), f"{model_id}: '{rev}' 40 haneli commit SHA degil"


@pytest.mark.parametrize(
    "model_id",
    [
        "Qwen/Qwen2.5-1.5B-Instruct",      # train_lora.py + predict.py varsayilani
        "HuggingFaceTB/SmolLM2-135M-Instruct",  # train_lora.SMOKE_MODEL
        "Qwen/Qwen2.5-3B-Instruct",        # not defteri 8. hucre, prompted yarismaci
    ],
)
def test_OLCUMDE_kullanilan_her_model_PINLI(model_id):
    assert model_id in PINNED_REVISIONS, f"{model_id} olcumde kullaniliyor ama pinsiz"


def test_scriptlerin_VARSAYILANLARI_pin_listesiyle_uyusuyor():
    """Varsayilan model degisip pin listesi unutulursa burasi kirmizi yanar."""
    import train_lora

    assert train_lora.SMOKE_MODEL in PINNED_REVISIONS


def test_override_pini_EZER():
    assert revision_for("Qwen/Qwen2.5-1.5B-Instruct", "deadbeef") == "deadbeef"


def test_bilinmeyen_model_SESSIZ_KALMAZ(capsys):
    """Pinsiz kosu olabilir ama GORUNMEZ olamaz."""
    assert revision_for("someone/unknown-model") is None
    assert "UYARI" in capsys.readouterr().out


# --- tedarik zinciri yuzeyi (geri kayma korumasi) -----------------------------


def test_not_defteri_DEGISEBILIR_main_klonlamaz():
    src = _notebook_source()
    assert "--branch {PIN}" in src, "klon bir etikete/pine baglanmali"
    assert "PIN    =" in src, "PIN sabiti not defterinde tanimli olmali"
    # Cipplak `git clone -q https://...git {KOK}` geri gelmemeli.
    assert not re.search(r"git clone -q https://github\.com/\S+\.git \{KOK\}", src), \
        "pinsiz klon geri gelmis"


def test_not_defteri_ne_kostugunu_KAYDA_geciriyor():
    assert "git rev-parse HEAD" in _notebook_source()


def test_bitsandbytes_HER_IKI_yerde_de_pinli():
    """Not defteri ve COLAB.md ayni komutu tasiyor; biri guncellenip digeri unutulur."""
    colab_md = (ROOT / "COLAB.md").read_text(encoding="utf-8")
    for ad, metin in (("not defteri", _notebook_source()), ("COLAB.md", colab_md)):
        assert "bitsandbytes==" in metin, f"{ad}: bitsandbytes pinsiz"
        assert not re.search(r"bitsandbytes(?!==)(\s|$)", metin), \
            f"{ad}: pinsiz bir bitsandbytes referansi kalmis"


def test_pip_satirlari_IKI_dosyada_AYNI():
    """COLAB.md not defterini tarif ediyor; ayrisirlarsa biri yalan soyluyor demektir."""
    pat = re.compile(r"!pip install -q transformers==\S+.*")
    nb = pat.search(_notebook_source())
    md = pat.search((ROOT / "COLAB.md").read_text(encoding="utf-8"))
    assert nb and md, "pip satiri iki dosyada da bulunmali"
    assert nb.group(0).strip() == md.group(0).strip(), (
        f"pip satirlari ayrismis:\n  nb: {nb.group(0)}\n  md: {md.group(0)}"
    )
