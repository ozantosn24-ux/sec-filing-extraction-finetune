"""edgar.py — SEC yanitindan gelen degerlerin DOGRULANMASI.

Bu modulun testi HIC yoktu; 2026-08-05 guvenlik denetiminde ortaya cikti
(testler collect/explore_one/evaluate/extract_rules import ediyordu, edgar'i
hic etmiyordu). Iki kapi olculuyor:

  1. BICIM: `_id` ve `ciks` degerleri hem URL'e hem DOSYA ADINA giriyor.
     Dogrulanmazsa "../../x" ya da (Linux'ta) "/etc/cron.d/x" bir accession
     olarak gecebilir ve `split.py` hedef dizini `mkdir(parents=True)` ile
     yaratip disari yazar.
  2. REDIRECT: `SEC_EDGAR_UA` ad + e-posta tasir. requests cross-host
     redirect'te yalniz `Authorization`'i siler, `User-Agent`'i TASIR — yani
     sec.gov disina cikan bir redirect kisisel adresi ucuncu tarafa gonderirdi.

Kotu-niyetli girdiler UYDURMA, gecerli girdiler GERCEK: alt taraftaki regresyon
testi `data/interim/manifest.json`'daki 160 gercek kaydin TAMAMINI kapidan
gecirir. Asil risk bir aciktan cok, kapiyi fazla dar yapip boru hattini kirmak.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import edgar  # noqa: E402

CANARY_UA = "CANARY Ad Soyad canary@example.invalid"
GERCEK_ID = "0001104659-21-115953:tm2127186-2_424b5.htm"  # Vornado, manifest'ten
GERCEK_CIK = "0000899689"


class SahteYanit:
    """requests.Response'un bu modulde KULLANILAN yuzeyi kadari."""

    def __init__(self, status_code=200, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._payload = payload

    @property
    def is_redirect(self):
        return "Location" in self.headers and self.status_code in (301, 302, 303, 307, 308)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _payload(_id: str, cik: str = GERCEK_CIK) -> dict:
    return {
        "hits": {
            "hits": [
                {
                    "_id": _id,
                    "_source": {
                        "ciks": [cik],
                        "display_names": ["VORNADO REALTY TRUST  (VNO, VNORP)"],
                        "file_type": "424B5",
                        "file_date": "2021-09-15",
                    },
                }
            ]
        }
    }


def _ara(monkeypatch, _id: str, cik: str = GERCEK_CIK) -> list:
    monkeypatch.setattr(edgar, "_request", lambda *a, **k: SahteYanit(payload=_payload(_id, cik)))
    return list(edgar.search("q"))


# --- 1) Bicim kapisi ----------------------------------------------------------


def test_gecerli_id_KABUL_EDILIR(monkeypatch):
    hits = _ara(monkeypatch, GERCEK_ID)
    assert len(hits) == 1
    assert hits[0].accession == "0001104659-21-115953"
    assert hits[0].cik == "899689"  # bastaki sifirlar kirpilir


@pytest.mark.parametrize(
    "kotu_id",
    [
        "../../../../../Users/Public/pwn:doc.htm",   # goreli traversal (her platform)
        "/etc/cron.d/pwn:doc.htm",                   # POSIX mutlak yol (Colab/Kaggle)
        "..:doc.htm",
        "0001104659-21-115953:../evil.htm",          # primary_doc traversal
        "0001104659-21-115953:sub/dir/evil.htm",     # primary_doc yol ayraci
        "0001104659-21-115953:..\\evil.htm",         # ters bolu (Windows)
        "0001104659-21-115953:evil.htm:extra",       # ikinci iki nokta
        "1104659-21-115953:doc.htm",                 # kisa accession
        "0001104659-21-84905:doc.htm",               # eksik haneli seri
    ],
)
def test_BOZUK_kimlik_REDDEDILIR(monkeypatch, kotu_id):
    assert _ara(monkeypatch, kotu_id) == []


@pytest.mark.parametrize("kotu_cik", ["../../etc", "89x689", "", "0", "12345678901"])
def test_BOZUK_cik_REDDEDILIR(monkeypatch, kotu_cik):
    assert _ara(monkeypatch, GERCEK_ID, cik=kotu_cik) == []


def test_kapiyi_gecen_kayit_sec_gov_DISINA_CIKAMAZ(monkeypatch):
    """Kabul edilen bir hit'in turettigi URL'ler her zaman sec.gov'da kalmali."""
    hit = _ara(monkeypatch, GERCEK_ID)[0]
    assert edgar._host_allowed(hit.doc_url)
    assert edgar._host_allowed(hit.index_url)


# --- 2) Redirect / UA sizintisi -----------------------------------------------


@pytest.mark.parametrize(
    "url,izinli",
    [
        ("https://www.sec.gov/x", True),
        ("https://efts.sec.gov/x", True),
        ("https://sec.gov/x", True),
        ("https://evil-sec.gov/x", False),      # nokta yok -> ESLESMEMELI
        ("https://sec.gov.evil.com/x", False),  # alan adi sonda degil
        ("http://127.0.0.1/x", False),
    ],
)
def test_host_izin_listesi(url, izinli):
    assert edgar._host_allowed(url) is izinli


@pytest.fixture
def kayitli_get(monkeypatch):
    """requests.get'i kaydeden bir sahte ile degistir; UA'yi da ayarla."""
    monkeypatch.setenv("SEC_EDGAR_UA", CANARY_UA)
    monkeypatch.setattr(edgar.time, "sleep", lambda *_: None)
    cagrilar: list[tuple[str, dict]] = []

    def kur(yanit_veren):
        def sahte_get(url, params=None, headers=None, timeout=None, allow_redirects=None):
            assert allow_redirects is False, "redirect'ler ELDE takip edilmeli"
            cagrilar.append((url, dict(headers or {})))
            return yanit_veren(url)

        monkeypatch.setattr(edgar.requests, "get", sahte_get)
        return cagrilar

    return kur


def test_YABANCI_hosta_redirect_ISTEK_ATILMADAN_reddedilir(kayitli_get):
    def yanit(url):
        return SahteYanit(302, headers={"Location": "https://evil.example/collect"})

    cagrilar = kayitli_get(yanit)
    with pytest.raises(edgar.EdgarError, match="REDDEDILDI"):
        edgar._request("https://www.sec.gov/Archives/edgar/data/1/2/x.htm")

    # ASIL KANIT: yabanci host'a HIC istek atilmadi -> UA de gitmedi.
    assert cagrilar, "en az bir istek beklenirdi"
    assert all(edgar._host_allowed(u) for u, _ in cagrilar)
    assert not any("evil.example" in u for u, _ in cagrilar)


def test_yabanci_hosta_giden_istek_YOKSA_UA_da_sizmaz(kayitli_get):
    """UA'nin gercekten header'da oldugunu dogrula — yoksa ustteki test bos gecer."""
    cagrilar = kayitli_get(lambda url: SahteYanit(200, text="ok"))
    edgar._request("https://www.sec.gov/x")
    assert cagrilar[0][1]["User-Agent"] == CANARY_UA


def test_sec_gov_ICI_redirect_TAKIP_EDILIR(kayitli_get):
    """POZITIF KONTROL: kapi secici olmali, 'her redirect'i blokla' degil."""

    def yanit(url):
        if url.endswith("/eski"):
            return SahteYanit(301, headers={"Location": "https://www.sec.gov/yeni"})
        return SahteYanit(200, text="ok")

    cagrilar = kayitli_get(yanit)
    r = edgar._request("https://www.sec.gov/eski")
    assert r.text == "ok"
    assert [u for u, _ in cagrilar] == ["https://www.sec.gov/eski", "https://www.sec.gov/yeni"]


def test_redirect_DONGUSU_sinirlanir(kayitli_get):
    kayitli_get(lambda url: SahteYanit(302, headers={"Location": "https://www.sec.gov/dongu"}))
    with pytest.raises(edgar.EdgarError, match="redirect siniri"):
        edgar._request("https://www.sec.gov/dongu")


def test_host_reddi_TEKRAR_DENENMEZ(kayitli_get):
    """Host reddi gecici bir ariza degil; 3 kez denemek anlamsiz."""
    cagrilar = kayitli_get(lambda url: SahteYanit(302, headers={"Location": "https://evil.example/"}))
    with pytest.raises(edgar.EdgarError):
        edgar._request("https://www.sec.gov/x")
    assert len(cagrilar) == 1, f"tekrar denenmis: {len(cagrilar)} istek"


# --- 3) Regresyon: kapi GERCEK veriyi kirmiyor mu? ----------------------------


def test_GERCEK_manifest_kayitlarinin_TAMAMI_kapidan_gecer():
    """160 gercek SEC kaydi. Kapiyi fazla dar yapmak, aciktan daha olasi bir hata.

    Bu test kirmiziya donerse duzeltme degil KAPI yanlistir — once burasi bakilir.
    """
    manifest = json.loads((ROOT / "data" / "interim" / "manifest.json").read_text(encoding="utf-8"))
    kayitlar = manifest["train"] + manifest["test"]
    assert len(kayitlar) >= 100, f"manifest beklenenden kucuk: {len(kayitlar)}"

    for m in kayitlar:
        acc = m["accession"]
        doc = m["doc_url"].rsplit("/", 1)[-1]
        assert edgar.ACCESSION_RE.fullmatch(acc), f"accession reddedildi: {acc}"
        assert edgar._safe_doc_name(doc), f"primary_doc reddedildi: {doc}"
        assert edgar._host_allowed(m["doc_url"]), f"host reddedildi: {m['doc_url']}"
        assert edgar.CIK_RE.fullmatch(m["doc_url"].split("/edgar/data/")[1].split("/")[0])
