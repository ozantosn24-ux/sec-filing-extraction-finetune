"""Adim ② veri hatti testleri — sema normalizasyonu ve SFT seti insasi.

Fixture'lar GERCEK SEC belgelerinden; elle yazilmis ornek yok (test_locate.py ile
ayni kural). Bu dosyadaki her test, olculmus bir ariza turunu karsiliyor:
uydurulmus bir kenar durum degil, veri setinde gercekten yasanmis olan.

Veri seti testleri `data/interim` .gitignore'da oldugu icin veri yoksa ATLANIR —
depoyu klonlayan biri kodu test edebilir, veriyi uretene kadar veri testleri susar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from build_sft import FIELD_ORDER, target_json  # noqa: E402
from normalize_labels import derive_unit  # noqa: E402
from prompt import INSTRUCTION, build_prompt, normalize_span  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"


def fixture(name: str) -> str:
    lines = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    body = [ln for i, ln in enumerate(lines) if not (i < 6 and ln.startswith("#"))]
    return "\n".join(body)


# --- derive_unit: birim turetme -----------------------------------------------


def test_adr_kalibi_depositary_SAYILMAZ():
    """En pahali tuzak: "depositary" kelimesi ADR kalibinda da geciyor.

    Alpine Income belgesinde "American Depositary Receipts (ADRs)" yalnizca adi
    hissenin kontrol-degisikligi maddesinde gecer — ihrac birimiyle ILGISI YOK.
    Kalip `depositary share|interest` diye DAR tutulmazsa bu kayit "depositary
    yapisi var" dalina duser ve cozulmemis kalir. Olculdu: 3 kayit boyle.
    """
    assert "Depositary Receipts" in fixture("adr_boilerplate")  # tuzak gercekten burada
    unit, _ = derive_unit(fixture("adr_boilerplate"))
    assert unit == "share"


def test_ADS_gorulurse_KARAR_VERMEZ():
    """"American Depositary Shares" korpusta YOK (0/160) — geldiginde dogru
    davranis onu ayiklayip "share" demek DEGIL, durup operatore birakmaktir:
    ADS gercekten depositary-benzeri bir birimdir.

    Bu testi yazdiran sey mutasyon denetimi: onceki surumde ADR/ADS ifadesini
    metinden silen bir on-temizlik vardi ve hicbir test onu tutmuyordu.
    """
    unit, _ = derive_unit("We are offering American Depositary Shares, "
                          "each representing one Preferred Share.")
    assert unit is None


def test_gercek_depositary_yapisi_KARAR_VERMEZ():
    """AGNC: gercek depositary yapisi -> script SUSAR, uydurmaz.

    Oran (1/1000) metinden okunmali; script tahmin etmektense operatore birakir.
    """
    unit, neden = derive_unit(fixture("depositary_structure"))
    assert unit is None
    assert "depositary" in neden.lower()


def test_ortaklik_preferred_units_unit_olur():
    """Energy Transfer LP: hisse degil BIRIM satiyor. "share" demek ayrimi siler."""
    unit, _ = derive_unit(fixture("preferred_units_lp"))
    assert unit == "unit"


def test_imtiyazli_ifadesi_yoksa_KARAR_VERMEZ():
    """Pozitif dayanak yoksa susar — metnin YOKLUGUNDAN "share" uretmez."""
    unit, _ = derive_unit("This prospectus relates to our common stock offering.")
    assert unit is None


# --- normalize_span: gorunmez karakterler -------------------------------------


def test_sifir_genislikli_bosluk_dusurulur():
    """U+200B: 1.937 adet olculdu. `\\s+` bunu TUTMAZ (kategori Cf), regex kirar."""
    assert normalize_span("per ​ share") == "per share"
    assert "​" not in normalize_span("$25.00​ per share")


def test_satir_yapisi_KORUNUR():
    """Tablo duzeni anlam tasiyor; `\\s+` ile ezmek kapak tablosunu duzlestirir."""
    assert normalize_span("Total\n\n $900,000") == "Total\n\n $900,000"


def test_normalize_span_idempotent():
    once = normalize_span(fixture("preferred_units_lp"))
    assert normalize_span(once) == once


def test_prompt_temiz_span_tasir():
    """Egitim girdisi ile eval girdisi ayni fonksiyondan cikar."""
    p = build_prompt("A ​ B")
    assert p.startswith(INSTRUCTION)
    assert "​" not in p
    assert p.endswith("A B")


# --- target_json: hedef dizgi -------------------------------------------------


def test_hedef_13_alan_sabit_sirada():
    """Anahtar sirasi sabit olmazsa tam-eslesme metrigi bicime duyarli olur."""
    out = json.loads(target_json({"is_preliminary": True}))
    assert list(out.keys()) == FIELD_ORDER
    assert len(out) == 13


def test_eksik_alan_null_olur_sessizce_DUSMEZ():
    """Anahtar kumesi her kayitta ayni; eksik alan atlanmaz, null yazilir."""
    out = json.loads(target_json({}))
    assert all(out[f] is None for f in FIELD_ORDER)


def test_hedef_kompakt():
    """Girinti ve bosluk token yakar; hedef tek satir."""
    s = target_json({"series": "B"})
    assert "\n" not in s and ", " not in s and '": ' not in s


# --- veri seti degismezleri (veri yoksa atlanir) ------------------------------


def _rows(split: str) -> list[dict]:
    f = PROCESSED / f"sft_{split}.jsonl"
    if not f.exists():
        pytest.skip(f"{f.relative_to(ROOT)} yok — once `python src/build_sft.py`")
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


# dev istege bagli (`build_sft.py --no-dev`); varsa TUM degismezler onu da kapsar.
SPLITS = ("train", "dev", "test") if (PROCESSED / "sft_dev.jsonl").exists() else ("train", "test")


def test_veri_tek_anahtar_sekli():
    """Model TEK bir cikti sekli ogrenmeli. Olculdu: 42 kayitta `offered_unit`
    anahtari HIC yoktu (null degil, yok) — normalize_labels.py bunu kapatti."""
    shapes = {tuple(json.loads(r["completion"]).keys())
              for split in SPLITS for r in _rows(split)}
    assert len(shapes) == 1
    assert list(shapes.pop()) == FIELD_ORDER


def test_sirket_ortusmesi_YOK():
    """Bolmenin cekirdek iddiasi. Belge degil SIRKET bazinda ayrilir.

    UC cift de kontrol edilir. train<->dev'i atlamak, dev'i bir secim araci
    olmaktan cikarip ikinci bir egitim setine cevirirdi: ayni ihraccinin kalip
    metni hem egitimde hem secimde gorunurse dev skoru siser ve "hangi epoch
    daha iyi" sorusunun cevabi ezberi olcer.
    """
    sirket = {s: {r["company_key"] for r in _rows(s)} for s in SPLITS}
    for a, b in (("train", "test"), ("train", "dev"), ("dev", "test")):
        if a in sirket and b in sirket:
            assert not (sirket[a] & sirket[b]), f"SIZINTI {a}<->{b}: {sirket[a] & sirket[b]}"


def test_her_etiketin_SIRKETI_BILINIYOR():
    """Bolme garantisi sirket kimligine dayanir; kimlik yoksa garanti de yok.

    Olculdu: 3 accession manifest.json'da ve documents.jsonl'de YOK (2. dalga
    etiketlemesi manifest'e islenmemis) ve `data/interim/` .gitignore'da oldugu
    icin kaynak geri getirilemiyor — bu yuzden `data/company_keys_extra.json`
    git'te tutuluyor. Bu test o dosya kaybolursa/bayatlarsa sessiz kalmaz.
    """
    from build_sft import LABEL_DIR, company_keys

    keys = company_keys()
    # Etiket DIZINLERI ikidir (train/, test/); dev onlarin uzerinde bir gorunum,
    # dolayisiyla burada kaynak dizinler taranir.
    eksik = [f"{split}/{p.stem}" for split in ("train", "test")
             for p in sorted((LABEL_DIR / split).glob("*.json")) if p.stem not in keys]
    assert not eksik, f"sirketi bilinmeyen kayit: {eksik}"


def test_sirket_anahtari_MASKELENMEMIS():
    """'?' gibi bir yer-tutucu iki bolmede birden gorunup ortusme kontrolunu
    hem sahte-pozitif hem sahte-negatif yapabiliyordu (ilk surumde oldu)."""
    for split in SPLITS:
        for r in _rows(split):
            assert r["company_key"] and r["company_key"] != "?"


def test_accession_ortusmesi_YOK():
    acc = {s: {r["accession"] for r in _rows(s)} for s in SPLITS}
    for a, b in (("train", "test"), ("train", "dev"), ("dev", "test")):
        if a in acc and b in acc:
            assert not (acc[a] & acc[b]), f"{a}<->{b}: {acc[a] & acc[b]}"


def test_dev_dosyasi_veriyle_AYNI_seyi_soyluyor():
    """`data/dev_split.json` git'te takip ediliyor, `sft_dev.jsonl` degil.

    Bayatlarsa "secim hangi kayitlarda yapildi" sorusu sonradan cevaplanamaz ve
    olcum tekrar-uretilemez hale gelir — company_keys_extra.json ile ayni gerekce.
    """
    if "dev" not in SPLITS:
        pytest.skip("dev bolmesi yok (--no-dev)")
    kayit = json.loads((ROOT / "data" / "dev_split.json").read_text(encoding="utf-8"))
    rows = _rows("dev")
    assert set(kayit["accessions"]) == {r["accession"] for r in rows}
    assert set(kayit["companies"]) == {r["company_key"] for r in rows}


def test_dev_train_uzerinde_bir_GORUNUM():
    """Dev'in kaynak dosyalari tasinmadi; tasinsaydi manifest ve tekrar-uretim
    bozulurdu. Kayitlar bunu `source_split` ile tasir."""
    if "dev" not in SPLITS:
        pytest.skip("dev bolmesi yok (--no-dev)")
    assert all(r["source_split"] == "train" for r in _rows("dev"))


def test_abstention_dilimi_HER_IKI_BOLMEDE_var():
    """G13: abstention ornekleri cikarilirsa model "bulamayinca uydur" ogrenir.
    Bu setin en ayirt edici parcasi bunlar — sessizce sifira dusmemeli."""
    for split in SPLITS:
        n = sum(1 for r in _rows(split) if r["meta"]["abstention"])
        assert n > 0, f"{split}: abstention ornegi kalmamis"


def test_zor_vaka_dilimi_var():
    """par_value ↔ liquidation_preference ayrimi projenin var olus sebebi;
    adim ③ bunu ayri raporlayacak, dilim bos olamaz."""
    for split in SPLITS:
        assert any(r["meta"]["hard_case_par_vs_liq"] for r in _rows(split))


def test_her_hedef_gecerli_JSON():
    for split in SPLITS:
        for r in _rows(split):
            obj = json.loads(r["completion"])
            assert len(obj) == 13


def test_promptta_gorunmez_karakter_YOK():
    for split in SPLITS:
        for r in _rows(split):
            assert "​" not in r["prompt"]


def test_prompt_ve_messages_AYNI_metni_tasir():
    """Iki bicim birlikte yaziliyor (TRL surum farki icin); ayrismalari
    sessiz bir egitim/eval uyusmazligi olurdu."""
    for split in SPLITS:
        for r in _rows(split):
            assert r["messages"][0]["content"] == r["prompt"]
            assert r["messages"][1]["content"] == r["completion"]


def test_her_kaydin_span_dosyasi_VAR():
    """Etiket kaynak-i hakikat; oksuz span sete sizmamali (olculdu: 10 oksuz span).

    Dosya yolu `source_split`'ten okunur, `split`'ten DEGIL: dev bir dizin degil,
    train uzerinde bir gorunum — span'leri `spans/train/` altinda durur.
    """
    for split in SPLITS:
        for r in _rows(split):
            src = r.get("source_split", split)
            assert (ROOT / "data" / "interim" / "spans" / src / f"{r['accession']}.txt").exists()
