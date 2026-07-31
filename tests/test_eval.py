"""Olcum takimi ve kural-tabanli yarismaci testleri.

Bir metrik, olctugu seyi yanlis olcerse sessizce yanlis bir sonuc ilan eder ve
kimse fark etmez — bu yuzden metrigin KENDISI test ediliyor. Ozellikle:
"her alana null yazan" dejenere bir model yuksek skor ALMAMALI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from evaluate import FIELD_ORDER, esit, parse_prediction, score  # noqa: E402
from extract_rules import extract  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    lines = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    return "\n".join(ln for i, ln in enumerate(lines) if not (i < 6 and ln.startswith("#")))


def tam(**over) -> dict:
    base = {f: None for f in FIELD_ORDER}
    base["is_preliminary"] = False
    base.update(over)
    return base


# --- parse_prediction: sema gecerliligi bir METRIK ----------------------------


def test_bozuk_json_ayrisamaz():
    obj, ihlal = parse_prediction("{series: B,}")
    assert obj is None and ihlal


def test_markdown_citesi_TOLERE_ama_KAYDEDILIR():
    """Talimat aciktan "no markdown fence" diyor. Tolere etmemek olcumu
    bicimlendirme uzerinden carpitirdi; kaydetmemek ihlali gizlerdi."""
    obj, ihlal = parse_prediction("```json\n" + json.dumps(tam()) + "\n```")
    assert obj is not None
    assert any("cite" in i for i in ihlal)


def test_eksik_alan_ihlal():
    d = tam()
    d.pop("series")
    _, ihlal = parse_prediction(json.dumps(d))
    assert any("eksik alan" in i for i in ihlal)


def test_yanlis_tip_ihlal():
    """"25.00" ile 25.00 ayni sey degil: biri metin, digeri sayi."""
    _, ihlal = parse_prediction(json.dumps(tam(liquidation_preference_usd="25.00")))
    assert any("sayi degil" in i for i in ihlal)


def test_enum_disi_ihlal():
    _, ihlal = parse_prediction(json.dumps(tam(dividend_frequency="biweekly")))
    assert any("enum disi" in i for i in ihlal)


def test_is_preliminary_null_olamaz():
    _, ihlal = parse_prediction(json.dumps(tam(is_preliminary=None)))
    assert any("is_preliminary" in i for i in ihlal)


def test_temiz_cikti_ihlalsiz():
    obj, ihlal = parse_prediction(json.dumps(tam(series="B")))
    assert obj is not None and ihlal == []


# --- esit: deger karsilastirmasi ----------------------------------------------


def test_sayi_tipten_bagimsiz():
    """25 ile 25.0 ayni degerdir; tip farki hata sayilmamali."""
    assert esit("liquidation_preference_usd", 25, 25.0)
    assert esit("shares_offered", 1000, 1000)


def test_farkli_sayi_ESIT_DEGIL():
    """Bu testsiz `esit` her zaman True dondurebilir ve tum skorlar %100 cikardi
    — mutasyon denetimi tam olarak bunu yakaladi."""
    assert not esit("liquidation_preference_usd", 25.0, 1000.0)
    assert not esit("par_value_usd", 0.01, 25.0)
    assert not esit("shares_offered", 12_000_000, 12_000)


def test_null_esitligi():
    assert esit("series", None, None)
    assert not esit("series", None, "B")
    assert not esit("series", "B", None)


# --- score: metrigin KENDISI --------------------------------------------------


def _preds(objs: dict[str, dict]) -> list[dict]:
    return [{"accession": a, "raw": json.dumps(o)} for a, o in objs.items()]


def test_hep_null_yazan_model_ODULLENDIRILMEZ():
    """Alanlarin cogu null oldugu icin "hep null" diyen model yuksek GENEL
    dogruluk alir. Dogru abstention ayri durmazsa bu gorunmez olurdu.

    Beklenen imza: abstention %100, ama kacirma da %100 ve TAM kayit 0.
    """
    gold = {"a": tam(series="B", coupon_rate_pct=6.5, is_preliminary=False)}
    s = score(_preds({"a": tam(is_preliminary=False)}), gold)
    assert s["abstention"] == (s["abstention"][1], s["abstention"][1])  # %100
    assert s["uydurma"][0] == 0
    # payda 3: series + coupon + is_preliminary (False de DOLU bir degerdir)
    assert s["kacirma"] == (2, 3)          # series ve coupon kacirildi
    assert s["tam_kayit"] == 0             # ve hicbir kayit tam degil


def test_uydurma_ayri_olculur():
    gold = {"a": tam(is_preliminary=False)}
    s = score(_preds({"a": tam(series="B", is_preliminary=False)}), gold)
    assert s["uydurma"][0] == 1
    assert s["abstention"][0] == s["abstention"][1] - 1


def test_ayrisamayan_cikti_TUM_alanlari_kaybeder():
    """Bozuk cikti atlanirsa, gecersiz JSON ureten model paydadan dusurulerek
    ODULLENDIRILIR. Ayrisamayan cikti = bos tahmin = tum dolu alanlar kacirildi."""
    gold = {"a": tam(series="B", is_preliminary=False)}
    s = score([{"accession": "a", "raw": "not json at all"}], gold)
    assert s["sema_gecerli"] == 0
    assert s["tam_kayit"] == 0
    assert s["kacirma"] == (2, 2)  # series ve is_preliminary: ikisi de kacirildi


def test_zor_vaka_dilimi_yalniz_IKISI_DE_dolu_kayitlarda():
    """par<->liq dilimi, ikisinin birlikte gectigi kayitlar icin tanimli."""
    gold = {"a": tam(par_value_usd=0.01, liquidation_preference_usd=25.0),
            "b": tam(series="B")}
    s = score(_preds({"a": tam(par_value_usd=0.01, liquidation_preference_usd=25.0),
                      "b": tam(series="B")}), gold)
    assert s["zor_vaka"] == (2, 2)  # yalniz "a"nin iki alani


def test_unit_vakasi_ISABET_ISKA_olarak():
    """Tek ornek; yuzde olarak sunmak olcumu sisirir."""
    gold = {"a": tam(offered_unit="unit")}
    assert score(_preds({"a": tam(offered_unit="unit")}), gold)["unit_vakasi"] == "ISABET"
    assert "ISKA" in score(_preds({"a": tam(offered_unit="share")}), gold)["unit_vakasi"]


# --- extract_rules: kural-tabanli yarismaci -----------------------------------


def test_kural_depositary_yapisini_tanir():
    got = extract(fixture("depositary_structure"))
    assert got["offered_unit"] == "depositary_share"


def test_kural_LP_unit_tanir():
    got = extract(fixture("preferred_units_lp"))
    assert got["offered_unit"] == "unit"
    assert got["liquidation_preference_usd"] == 1000.0


def test_kural_par_degerini_tasfiye_tercihi_SANMAZ():
    """Projenin var olus sebebi. Alpine parcasi "par value $0.01 per share" ve
    "$25.00 per share" ifadelerini BIRLIKTE tasiyor — naif kural 0,01'i alir."""
    got = extract(fixture("adr_boilerplate"))
    assert got["liquidation_preference_usd"] != 0.01


def test_kural_sessizlikten_false_URETMEZ():
    """LABELING.md §G: bool yalnizca acikca olumsuzlanirsa false, sessizlik null."""
    got = extract("The Series A Preferred Stock is offered at $25.00 per share.")
    assert got["convertible"] is None
    assert got["cumulative"] is None


def test_kural_non_cumulative_false_yapar():
    got = extract("7.00% Series B Non-Cumulative Perpetual Preferred Stock")
    assert got["cumulative"] is False


def test_kural_no_par_value_null():
    """§H: "par degeri yok" bir tutarin YOKLUGU; 0.00 farkli bir iddiadir."""
    got = extract("Series A Preferred Stock, without par value, $25.00 per share")
    assert got["par_value_usd"] is None


def test_kural_ADI_HISSENIN_par_degerini_ALMAZ():
    """Albemarle: imtiyazli "without par value" ama ADI HISSE "par value $0.01
    per share" — ikisi ayni span'de, 894 karakter arayla. Altin cevap null.

    "no par value" kontrolu once kosmazsa kural adi hissenin 0,01'ini imtiyazlinin
    par degeri sanar. Duz bir "without par value" cumlesi bu tuzagi kurmuyordu
    (mutasyon denetimi yakaladi) — gercek belgede iki ifade birlikte bulunuyor.
    """
    got = extract(fixture("no_par_value_trap"))
    assert got["par_value_usd"] is None


def test_kural_kredi_faizini_kupon_SANMAZ():
    """Olculdu: UMH'de "1.50% to 2.20% (depending on our overall leverage ratio)"
    bir kredi marji. Kupon araligi disinda ve menkul kiymete demirli degil."""
    got = extract("interest at 1.50% to 2.20% depending on our overall leverage ratio")
    assert got["coupon_rate_pct"] is None


def test_kural_oy_gucunu_kupon_SANMAZ():
    """FAT Brands: "55.5% of the combined voting power of our Class A Common Stock".
    Yuzde menkul kiymet kelimesine DEMIRLI (Class), yani konum kontrolu yetmiyor —
    2-15% araligi olmasa kupon diye okunurdu."""
    got = extract(fixture("out_of_range_pct"))
    assert got["coupon_rate_pct"] != 55.5


def test_kural_depositary_birim_basi_tercihi_alir():
    """Merchants Bancorp: "$1,000 per share (equivalent to $25 per depositary share)".
    Teklif edilen birim depositary hisse -> dogru cevap 25.

    Metinde ayrica BASKA bir serinin "liquidation preference $1,000" ifadesi var;
    depositary onceligi olmadan kural onu kapar. LABELING.md §F'nin "buyuk rakama
    yonelme" hatasi tam olarak budur (ilk turda 24/27 depositary kaydi boyle bozuldu).
    """
    got = extract(fixture("depositary_liq_per_unit"))
    assert got["offered_unit"] == "depositary_share"
    assert got["liquidation_preference_usd"] == 25.0


def test_kural_cikti_semasi_TAM():
    got = extract(fixture("depositary_structure"))
    assert list(got.keys()) == FIELD_ORDER
