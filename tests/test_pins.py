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
# Kapsami TEK dosyaya degil DIZINE bagla: 2026-08-19'da ikinci bir defter eklendi
# (constrained_decoding.ipynb) ve tek-dosyaya bagli testler onu HIC gormezdi —
# pinsiz klonlayan yeni bir defter sessizce girebilirdi.
NOTEBOOKS = sorted((ROOT / "colab").glob("*.ipynb"))


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


def test_HICBIR_from_pretrained_pinsiz_KALMASIN():
    """src/ genelinde hub'dan model/tokenizer ceken her cagri revision almali.

    Bu test, 08-05'te `measure_tokens.py`'yi ATLADIGIM icin var: pinleri elle
    tek tek gezmek bir dosyayi kacirmaya acik. Kapsami dosya listesine degil
    KAYNAGIN KENDISINE bagla ki yeni bir cagri eklendiginde de yakalansin.
    """
    # Yerel dizinden yuklenen adaptor: revision kavrami YOK (HF deposu degil).
    IZINLI = {("predict.py", "PeftModel.from_pretrained")}

    ihlal = []
    for py in sorted((ROOT / "src").glob("*.py")):
        metin = py.read_text(encoding="utf-8")
        for m in re.finditer(r"(\w+)\.from_pretrained\s*\(", metin):
            # cagrinin kapanis parantezine kadar olan metni al
            i = m.end() - 1
            derinlik, j = 0, i
            while j < len(metin):
                if metin[j] == "(":
                    derinlik += 1
                elif metin[j] == ")":
                    derinlik -= 1
                    if derinlik == 0:
                        break
                j += 1
            cagri = metin[m.start():j + 1]
            anahtar = (py.name, f"{m.group(1)}.from_pretrained")
            if anahtar in IZINLI:
                continue
            if "revision=" not in cagri:
                satir = metin[:m.start()].count("\n") + 1
                ihlal.append(f"{py.name}:{satir}  {m.group(1)}.from_pretrained(...)")

    assert not ihlal, "revision'siz from_pretrained cagrisi:\n  " + "\n  ".join(ihlal)


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


# --- TUM defterler ayni pin kuralina tabi ------------------------------------


def _defter_kaynagi(nb) -> str:
    hucreler = json.loads(nb.read_text(encoding="utf-8"))["cells"]
    return chr(10).join("".join(c.get("source", [])) for c in hucreler)


@pytest.mark.parametrize("nb", NOTEBOOKS, ids=[p.name for p in NOTEBOOKS])
def test_HER_defter_pinli_etiketten_klonluyor(nb):
    """Yeni bir defter eklenince de gecerli: kod DEGISEBILIR main'den gelmez."""
    src = _defter_kaynagi(nb)
    if "git clone" not in src:
        pytest.skip(f"{nb.name} depoyu klonlamiyor")
    assert "--branch {PIN}" in src, f"{nb.name}: klon bir etikete baglanmali"
    # Tirnak tipi ve bosluk serbest: egitim defteri `PIN    = 'v1.0-measured'`,
    # yeni defter `PIN = "v1.2-constrained"` yaziyor. Onemli olan bir SURUM
    # etiketine baglanmis olmasi, yazim bicimi degil.
    assert re.search(r"""PIN\s*=\s*['"]v[\d.]""", src), f"{nb.name}: PIN bir surum etiketi olmali"
    assert not re.search(r"git clone -q https://github\.com/\S+\.git", src), f"{nb.name}: pinsiz klon"


@pytest.mark.parametrize("nb", NOTEBOOKS, ids=[p.name for p in NOTEBOOKS])
def test_HER_defter_ne_kostugunu_KAYDA_geciriyor(nb):
    src = _defter_kaynagi(nb)
    if "git clone" not in src:
        pytest.skip(f"{nb.name} depoyu klonlamiyor")
    assert "git rev-parse HEAD" in src, f"{nb.name}: kunye yok"
