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
