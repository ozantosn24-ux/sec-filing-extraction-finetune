"""SEC EDGAR erisim katmani — arama, belge indirme, tempo kontrolu.

SEC adil erisim kurallari (https://www.sec.gov/os/webmaster-faq#developers):
  * Kendini TANITAN bir User-Agent sart (iletisim bilgisi iceren).
  * Saniyede en fazla 10 istek.

UA rotasyonu KULLANILMAZ — SEC'in istedigi tam tersi: sabit, kimligi belli bir UA.
Deger `SEC_EDGAR_UA` ortam degiskeninden okunur, koda gomulmez (repo ileride
public olacak; kisisel e-posta commit edilmez).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urljoin, urlparse

import requests

EFTS_SEARCH = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# SEC tavani 10 req/s; muhafazakar davraniyoruz.
MIN_REQUEST_GAP_S = 0.25

# EFTS yanitindan gelen degerler DOGRULANMADAN hem URL'e hem DOSYA YOLUNA giriyordu
# (guvenlik denetimi 2026-08-05). `_id` "../../x:doc.htm" olsaydi span/raw yazimi
# repo disina tasardi — `split.py` hedef dizini `mkdir(parents=True)` ile YARATIYOR,
# yani var olmayan bir agaca da yazabilirdi. Linux'ta (Colab/Kaggle) mutlak yol da
# geciyordu: "/etc/cron.d/x" iki nokta icermedigi icin partition(":")'dan saglam cikar.
# Bicim kapisi, yanit butunlugu bozulmus bir EFTS'e karsi tek savunma.
ACCESSION_RE = re.compile(r"\d{10}-\d{2}-\d{6}")
CIK_RE = re.compile(r"\d{1,10}")
DOC_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")

# Redirect yalniz SEC icinde kalabilir — gerekce `_get` docstring'inde.
ALLOWED_HOST = "sec.gov"
MAX_REDIRECTS = 5

_last_request_at = 0.0


class EdgarError(RuntimeError):
    pass


def _host_allowed(url: str) -> bool:
    """Yalniz sec.gov ve alt alan adlari. 'evil-sec.gov' ESLESMEZ (nokta sart)."""
    host = (urlparse(url).hostname or "").lower()
    return host == ALLOWED_HOST or host.endswith("." + ALLOWED_HOST)


def _safe_doc_name(name: str) -> bool:
    """`primary_doc` bir DOSYA ADI olmali: yol ayraci, ust-dizin, surucu harfi YOK."""
    if not name or len(name) > 128 or ".." in name:
        return False
    return bool(DOC_NAME_RE.fullmatch(name))


def user_agent() -> str:
    ua = os.environ.get("SEC_EDGAR_UA", "").strip()
    if not ua:
        raise EdgarError(
            "SEC_EDGAR_UA ortam degiskeni bos. SEC kendini tanitan bir User-Agent "
            'istiyor. Ornek: SEC_EDGAR_UA="Ad Soyad ad@ornek.com"'
        )
    return ua


def _throttle() -> None:
    global _last_request_at
    gap = time.monotonic() - _last_request_at
    if gap < MIN_REQUEST_GAP_S:
        time.sleep(MIN_REQUEST_GAP_S - gap)
    _last_request_at = time.monotonic()


def _get(url: str, params: dict | None, headers: dict) -> requests.Response:
    """Redirect'leri ELDE takip et; her adimda hedefi ISTEKTEN ONCE dogrula.

    🔴 Neden `allow_redirects=False`: requests cross-host redirect'te yalniz
    `Authorization` header'ini siliyor, ozel header'lari TASIYOR — `User-Agent`
    dahil. (requests 2.32.5 `Session.rebuild_auth` okundu VE loopback'te iki
    sunucuyla olculdu, 2026-08-05: Authorization dusuruldu, UA hedefe ulasti.)

    `SEC_EDGAR_UA`, SEC'in adil-erisim kurali geregi ad + e-posta tasir. sec.gov
    disina cikan TEK bir redirect onu ucuncu tarafa gonderirdi. Yanit geldikten
    sonra `r.url`'i kontrol etmek gec kalir: header zaten gitmis olur. Bu yuzden
    dogrulama istekten ONCE yapilir.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not _host_allowed(current):
            raise EdgarError(
                f"sec.gov disi host REDDEDILDI: {urlparse(current).hostname!r} "
                f"— istek atilmadi, User-Agent gonderilmedi"
            )
        r = requests.get(current, params=params, headers=headers, timeout=30,
                         allow_redirects=False)
        if not r.is_redirect:
            if 300 <= r.status_code < 400:
                raise EdgarError(f"{current}: Location'siz {r.status_code} yaniti")
            return r
        current = urljoin(current, r.headers["Location"])
        params = None  # sorgu dizesi artik Location'da tasinir
        _throttle()
    raise EdgarError(f"{url}: {MAX_REDIRECTS} redirect siniri asildi")


def _request(url: str, params: dict | None = None, retries: int = 3) -> requests.Response:
    headers = {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    last_exc: Exception | None = None
    for attempt in range(retries):
        _throttle()
        try:
            r = _get(url, params, headers)
            r.raise_for_status()
            return r
        except EdgarError:
            raise  # host reddi/redirect ihlali GECICI DEGIL — tekrar denemek anlamsiz
        except Exception as exc:  # noqa: BLE001 — tek noktada raporlanir
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise EdgarError(f"{url} alinamadi: {last_exc}")


@dataclass(frozen=True)
class FilingHit:
    """EFTS arama sonucundan tek bir dosyalama."""

    accession: str
    cik: str
    company: str
    form: str
    filed_date: str
    primary_doc: str

    @property
    def doc_url(self) -> str:
        acc_nodash = self.accession.replace("-", "")
        return f"{ARCHIVES}/{self.cik}/{acc_nodash}/{self.primary_doc}"

    @property
    def index_url(self) -> str:
        acc_nodash = self.accession.replace("-", "")
        return f"{ARCHIVES}/{self.cik}/{acc_nodash}/"


def search(
    query: str,
    forms: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
) -> Iterator[FilingHit]:
    """EDGAR tam-metin aramasi. `query` tirnakli ifade olabilir: '"Cumulative Preferred"'."""
    params: dict[str, str] = {"q": query}
    if forms:
        params["forms"] = forms
    if start and end:
        params.update({"dateRange": "custom", "startdt": start, "enddt": end})

    payload = _request(EFTS_SEARCH, params=params).json()
    hits = payload.get("hits", {}).get("hits", [])
    for hit in hits[:limit]:
        src = hit.get("_source", {})
        raw_id = hit.get("_id", "")
        # _id bicimi: "0001234567-25-000123:dosya.htm"
        accession, _, primary_doc = raw_id.partition(":")
        ciks = src.get("ciks") or []
        cik = str(ciks[0]).lstrip("0") if ciks else ""
        display = src.get("display_names") or []
        company = str(display[0]).split(" (CIK")[0].strip() if display else ""
        if not (accession and cik and primary_doc):
            continue
        # 🔴 BICIM KAPISI — bu uc deger hem URL'e hem DOSYA ADINA giriyor.
        # Bosluk kontrolu yetmiyordu: "../../x" da, "/etc/cron.d/x" de doluydu.
        if not (
            ACCESSION_RE.fullmatch(accession)
            and CIK_RE.fullmatch(cik)
            and _safe_doc_name(primary_doc)
        ):
            # Sessizce dusurmek bu repoda kurala aykiri (bkz. collect.py kayip
            # olcumu). Normalde sifir olmali; bir sey basiyorsa BAKILMALI.
            # `!r` kontrol karakterlerini kacisla yazar — terminal escape enjeksiyonu yok.
            print(f"  ATLANDI (gecersiz SEC kimligi): _id={raw_id[:80]!r}")
            continue
        yield FilingHit(
            accession=accession,
            cik=cik,
            company=company,
            form=src.get("file_type", ""),
            filed_date=src.get("file_date", ""),
            primary_doc=primary_doc,
        )


def fetch_document(hit: FilingHit) -> str:
    """Dosyalamanin birincil belgesini ham olarak indir (HTML ya da duz metin)."""
    return _request(hit.doc_url).text
