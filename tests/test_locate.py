"""Span konumlandirma ve metin normalizasyonu testleri.

Fixture'lar GERCEK SEC belgelerinden alinmis parcalardir (kunye her dosyanin
basinda: accession + sirket + URL). Elle yazilmis ornek YOK — cunku bu projede
bulunan hatalarin hepsi, uydurma ornekle degil gercek belgeyle ortaya cikti.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from collect import (  # noqa: E402
    COUPON_MAX,
    COUPON_MIN,
    SEARCH_LIMIT,
    SPAN_AFTER,
    SPAN_BEFORE,
    is_preferred_offering,
    locate_span,
    offering_key,
)
from explore_one import strip_html  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    """Kunye satirlarini (# ile baslayan bas blok) atarak gercek metni dondur."""
    lines = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    body = [ln for i, ln in enumerate(lines) if not (i < 6 and ln.startswith("#"))]
    return "\n".join(body)


# --- locate_span: fiyatlanmis baslik -----------------------------------------


def test_fiyatlanmis_baslik_bulunur():
    """NexPoint: '9.00% Series B Cumulative...' -> priced capa."""
    got = locate_span(fixture("priced_title"))
    assert got is not None
    span, offset, anchor = got
    assert anchor == "priced"
    assert "9.00%" in span
    assert "Series B" in span


def test_on_prospektus_bos_kupon_yakalanir():
    """M&T: 'Perpetual % Non-Cumulative Preferred Stock' — rakam YOK.

    Bu kayitlar kayip degil, ABSTENTION dilimidir: dogru cevap null.
    \\d+% capasi burada duser; ayri desen olmazsa belge tamamen kaybolur.
    """
    got = locate_span(fixture("preliminary_blank_coupon"))
    assert got is not None
    span, offset, anchor = got
    assert anchor == "preliminary"
    assert "Preferred Stock" in span


def test_depositary_yapi_capa_bulur():
    got = locate_span(fixture("depositary_structure"))
    assert got is not None
    assert "Depositary Shares" in got[0]


# --- locate_span: tuzaklar ----------------------------------------------------


def test_kupon_araligi_disindaki_yuzde_capa_OLMAZ():
    """Olculdu: UMH belgesinde '1.50% to 2.20% (depending on our overall leverage
    ratio)' bir KREDI FAIZI. Aralik dogrulamasi olmadan kupon sanilir."""
    metin = (
        "Borrowings bear interest at LIBOR plus 1.50% to 2.20% (depending on our "
        "overall leverage ratio) and the facility permits Preferred Stock issuance."
    )
    got = locate_span(metin)
    assert got is None, "kredi faizi kupon sanildi"


def test_makul_araligin_ustundeki_yuzde_reddedilir():
    metin = "Holders of 50% of the Preferred Stock may direct the trustee."
    assert locate_span(metin) is None


@pytest.mark.parametrize("kupon", [COUPON_MIN, 6.375, COUPON_MAX])
def test_arilik_ici_kuponlar_kabul_edilir(kupon):
    metin = f"{kupon}% Series A Cumulative Redeemable Preferred Stock offered hereby"
    got = locate_span(metin)
    assert got is not None and got[2] == "priced"


def test_american_depositary_share_imtiyazli_SAYILMAZ():
    """Biodexa ADS ihraci imtiyazli sanilmisti — tamamen baska enstruman."""
    metin = "5,050,808 American Depositary Shares Representing Ordinary Shares, Preferred"
    got = locate_span(metin)
    assert got is None or got[2] != "priced"


def test_arama_penceresi_disinda_capa_aranmaz():
    """Derin eslesmeler capraz kanitla curudu (WesBanco @68.336 oy hakki metni)."""
    dolgu = "x" * 25_000
    metin = dolgu + " 7.00% Series C Cumulative Preferred Stock"
    assert locate_span(metin) is None


# --- locate_span: dusmanca girdiler -------------------------------------------
#
# Yukaridaki tuzak testleri "yanlis capa secilmesin" diyor. Buradakiler baska bir
# soru soruyor: girdi BICIM olarak asiriya kacinca fonksiyon ne yapiyor? Uc vaka da
# uydurulmadi, korpusta OLCULDU (172 belge, `data/interim/documents.jsonl`):
#
#   full_len      min 33.357 · medyan 316.276 · max 994.748
#   span_offset   min 178 · max 19.711  (SEARCH_LIMIT'e 289 karakter kala!)
#   span_offset < SPAN_BEFORE olan belge sayisi: 126 / 172
#
# Yani "cok uzun belge" ve "capa belgenin en basinda" nadir kenar vaka DEGIL,
# korpusun normali. Fixture olarak dosya yazilmadi: bu depoda tests/fixtures/
# yalnizca GERCEK belge parcalarini tutar, sentetik girdi test icinde kurulur.

BASLIK_6375 = "6.375% Series A Cumulative Redeemable Preferred Stock offered hereby"


def test_asiri_uzun_belgede_span_TAVANI_asmaz():
    """Korpusun en uzun belgesi 994.748 karakter; span her zaman SPAN_BEFORE+AFTER.

    `text[:SEARCH_LIMIT]` ya da dondurulen dilim kaldirilirsa fonksiyon HATA VERMEZ —
    yalnizca yuz binlerce karakterlik bir span dondurur ve o span prompt'a girer.
    Kesme egitim tarafinda sessizce olur (bkz. max_length korumasi), yani hata
    ancak metriklerde 'model okuyamadi' gibi gorunur.
    """
    belge = "filler. " * 1000 + BASLIK_6375 + " tail. " * 140_000
    assert len(belge) > 900_000, "test kendi kurdugu belgeyi kucultmus olmasin"

    span, offset, anchor = locate_span(belge)

    assert anchor == "priced"
    assert offset == 8_000
    assert len(span) == SPAN_BEFORE + SPAN_AFTER


def test_capa_BASTAYKEN_pencere_belgenin_SONUNDAN_alinmaz():
    """`max(0, m.start() - SPAN_BEFORE)` clamp'i sicak yolda: 126/172 belgede
    capa ilk 800 karakterde.

    Clamp dusurulurse `text[-780 : 5200]` gibi bir dilim olusur; Python hata
    vermez, bos ya da belgenin SONUNDAN gelen bir pencere doner. Kapak sayfasi
    yerine arka sayfalari etiketleyen, tamamen makul GORUNEN bir veri seti.
    """
    belge = BASLIK_6375 + " rest of the cover page. " * 300

    span, offset, _ = locate_span(belge)

    assert offset == 0
    assert span.startswith("6.375%"), "pencere capanin oncesinden degil SONRASINDAN baslamis"
    assert len(span) == SPAN_AFTER  # clamp 0'a cekti, SPAN_BEFORE eklenmedi


@pytest.mark.parametrize(
    "metin",
    ["", "   \n\t   ", "12345", "%%%%", "Preferred"],
    ids=["bos", "yalnizca-bosluk", "yalnizca-rakam", "yalnizca-yuzde", "capasiz-kelime"],
)
def test_ickisiz_belge_COKMEZ_None_doner(metin):
    """Ihrac basligi yoksa cevap None — istisna degil, bos string de degil.

    Cagiran taraf (`collect.py`) None'i 'bu belge veri setine girmez' diye
    okuyor; burada istisna atmak toplama dongusunu ortadan kirardi.
    """
    assert locate_span(metin) is None


@pytest.mark.parametrize("kaydir", [-1, 0, 1, 2], ids=["bir-onceki", "tam-sinir", "bir-sonraki", "iki-sonraki"])
def test_SEARCH_LIMIT_siniri_ESLESMENIN_BITISINE_gore(kaydir):
    """Sinir, basligin basina degil regex eslesmesinin BITISINE gore isliyor.

    Onemli, cunku korpusun en derin capasi 19.711'de — sinira 289 karakter.
    Beklenen deger sabit yazilmiyor, ayni kuraldan turetiliyor; SEARCH_LIMIT
    degistiginde test kendini uyarliyor ama DAVRANIS degisirse yine kirilir.
    """
    bitis_ofseti = BASLIK_6375.index("Preferred") + len("Preferred")
    baslangic = SEARCH_LIMIT - bitis_ofseti + kaydir
    metin = "x" * baslangic + BASLIK_6375

    bulunmali = baslangic + bitis_ofseti <= SEARCH_LIMIT
    assert (locate_span(metin) is not None) is bulunmali


# --- offering_key -------------------------------------------------------------


def test_ayni_ihrac_ayni_anahtar():
    span = "9.00% Series B Cumulative Redeemable Preferred Stock"
    a = offering_key("NexPoint Real Estate Finance, Inc.  (NREF)", span)
    b = offering_key("NexPoint Real Estate Finance, Inc.  (NREF, NREF-PA)", span)
    assert a == b, "ticker listesi anahtari degistirmemeli"


def test_farkli_kupon_farkli_anahtar():
    a = offering_key("Strategy Inc", "10.00% Series A Perpetual Strife Preferred Stock")
    b = offering_key("Strategy Inc", "8.00% Series A Perpetual Strike Preferred Stock")
    assert a != b


def test_bilinen_sinir_ayni_kupon_ayni_seri_farkli_menkul():
    """Strategy Inc'in DORT imtiyazlisi da 'Series A'; ayrim isimde (Strife/Stride).

    offering_key bunlari AYIRAMAZ — bilinen ve belgelenmis sinir, hata degil.
    Bu test sinirin farkinda olundugunu sabitler; davranis degisirse haber verir.
    """
    a = offering_key("Strategy Inc", "10.00% Series A Perpetual Strife Preferred Stock")
    b = offering_key("Strategy Inc", "10.00% Series A Perpetual Stride Preferred Stock")
    assert a == b


# --- is_preferred_offering ----------------------------------------------------


def test_imtiyazli_suzgeci():
    assert is_preferred_offering(fixture("priced_title"))
    assert not is_preferred_offering("Common stock offering, no such security here.")


# --- strip_html: olculmus iki hata --------------------------------------------


def test_html_entity_cozulur():
    """Elle entity listesi eksik kaliyordu: &#147; &#146; &#160; metinde kaliyordu."""
    out = strip_html("<p>par value &#160;$0.01 &#147;Series B&#148;</p>")
    assert "&#" not in out
    assert "$0.01" in out


def test_unicode_bosluklar_normalize_edilir():
    """Korpusta OLCULEN kod noktalari: U+2003 x524, U+2007 x353, U+2009 x45,
    U+200A x26, U+2002 x16.

    `[ \\t\\xa0]+` bunlari kaciriyordu ve sonuc sinsiydi: metinde acikca yazan
    'par value' ifadesi aramada 0 eslesme donuyordu. Kural-tabanli baseline'i
    sessizce sakat birakir -> fine-tuned model haksiz kazanir, olcum yalan olur.
    """
    ham = "par value $0.01 per share here"
    out = strip_html(ham)
    for cp in (" ", " ", " ", " ", " "):
        assert cp not in out
    assert "par value $0.01 per share here" in out


def test_satir_yapisi_korunur():
    """Bosluk normalizasyonu satir sonlarini YUTMAMALI — belge yapisi bilgi tasir."""
    out = strip_html("<p>ilk satir</p><p>ikinci satir</p>")
    assert "\n" in out
