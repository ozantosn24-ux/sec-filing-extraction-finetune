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
import time
from dataclasses import dataclass
from typing import Iterator

import requests

EFTS_SEARCH = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# SEC tavani 10 req/s; muhafazakar davraniyoruz.
MIN_REQUEST_GAP_S = 0.25

_last_request_at = 0.0


class EdgarError(RuntimeError):
    pass


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


def _request(url: str, params: dict | None = None, retries: int = 3) -> requests.Response:
    headers = {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    last_exc: Exception | None = None
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            return r
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
