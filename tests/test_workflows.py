"""CI workflow'larinin GUVENLIK OZELLIKLERI geri kayiyor mu?

Guvenlik denetimi 2026-08-05, bulgu C-04 ("bagimlilik + statik analiz kor noktasi"):
gitleaks / pip-audit / CodeQL hicbiri kosmuyordu. 2026-08-19'da uctu de eklendi.
Buradaki testler o kontrollerin CALISTIGINI dogrulamaz — onu CI kosusu yapar.
Burada dogrulanan, kontrollerin ILERIDE SESSIZCE ZAYIFLAMAMASI:

  * bir `uses:` satiri SHA'dan etikete donerse (etiket oynatilabilir),
  * gitleaks indirmesinin checksum kapisi dusrse,
  * `--redact` kalkarsa (bu depo PUBLIC — Actions loglari da oyle; redaksiyonsuz bir
    bulgu, isin yakalamak icin var oldugu sirri yayinlar),
  * `fetch-depth: 0` kalkarsa (sig klon = tek commit taranir, is yine YESIL yanar),
  * bir workflow ust duzey `permissions` bildirmeyi birakirsa (varsayilan cok genis).

⭐ Kapsam dosya listesine degil KAYNAGA bagli: .github/workflows/*.yml ne varsa
taranir, yeni bir workflow eklendiginde de ayni kurallara girer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML yok; workflow testleri atlanir")

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = ROOT / ".github" / "workflows"

SHA40 = re.compile(r"^[0-9a-f]{40}$")
# `uses: owner/repo@ref  # yorum`  ya da  `uses: owner/repo/alt@ref`
USES_RE = re.compile(r"^\s*-?\s*uses:\s*(?P<action>[^@\s]+)@(?P<ref>\S+)(?P<rest>.*)$", re.M)


def _workflows() -> list[Path]:
    dosyalar = sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yaml"))
    assert dosyalar, "hic workflow bulunamadi — kapsam sessizce bosalmis olabilir"
    return dosyalar


def _metin(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _yaml(p: Path) -> dict:
    return yaml.safe_load(_metin(p))


WORKFLOWS = _workflows()
IDS = [p.name for p in WORKFLOWS]


# --- pinleme ------------------------------------------------------------------


@pytest.mark.parametrize("wf", WORKFLOWS, ids=IDS)
def test_her_uses_TAM_SHA_ile_pinli(wf):
    """Etiket pin degildir: `@v7` ust hesap ele gecerse baska koda yonlendirilebilir."""
    ihlal = []
    for m in USES_RE.finditer(_metin(wf)):
        if not SHA40.match(m.group("ref")):
            ihlal.append(f"{wf.name}: {m.group('action')}@{m.group('ref')}")
    assert not ihlal, "etikete pinli action:\n  " + "\n  ".join(ihlal)


@pytest.mark.parametrize("wf", WORKFLOWS, ids=IDS)
def test_her_pin_YANINDA_surumu_yaziyor(wf):
    """SHA okunamaz; yorumdaki surum kalkarsa pin bakim yapilamaz hale gelir."""
    ihlal = []
    for m in USES_RE.finditer(_metin(wf)):
        if not re.search(r"#\s*v\d", m.group("rest")):
            ihlal.append(f"{wf.name}: {m.group('action')} icin surum yorumu yok")
    assert not ihlal, "\n  ".join(ihlal)


@pytest.mark.parametrize("wf", WORKFLOWS, ids=IDS)
def test_workflow_UST_DUZEY_permissions_bildiriyor(wf):
    """Bildirilmezse depo varsayilani gecerli olur — bu isler icin fazla genis."""
    d = _yaml(wf)
    assert "permissions" in d, f"{wf.name}: ust duzey permissions yok"


# --- audit.yml'e ozel: kontrolun kendisi zayiflamasin -------------------------


AUDIT = WF_DIR / "audit.yml"


def _run_bloklari(wf: Path) -> list[str]:
    """Workflow'un CALISTIRDIGI kabuk satirlari — YORUMLAR DEGIL.

    Bu ayrimin bedeli olculdu: ilk surumde `--redact` dosya metninde araniyordu ve
    bayragi `run:` satirindan silen mutasyon YESIL kaldi, cunku ayni kelime hemen
    ustundeki aciklama yorumunda geciyordu. Kontrolu aciklamaya degil komuta bagla.
    """
    d = _yaml(wf)
    bloklar = []
    for job in d["jobs"].values():
        for adim in job.get("steps", []):
            if isinstance(adim.get("run"), str):
                bloklar.append(adim["run"])
    return bloklar


def _gitleaks_tarama_komutu() -> str:
    aday = [b for b in _run_bloklari(AUDIT) if "gitleaks git" in b]
    assert aday, "audit.yml icinde gitleaks tarama adimi yok"
    return "\n".join(aday)


def test_gitleaks_indirmesi_CHECKSUM_kapisindan_geciyor():
    metin = _metin(AUDIT)
    sha = re.search(r"GITLEAKS_SHA256:\s*([0-9a-f]{64})", metin)
    assert sha, "gitleaks tarball'i icin 64 haneli sha256 pini yok"
    indirme = [b for b in _run_bloklari(AUDIT) if "gitleaks.tar.gz" in b]
    assert indirme, "gitleaks indirme adimi bulunamadi"
    assert any("sha256sum -c" in b for b in indirme), "sha256 yaziliyor ama DOGRULANMIYOR"


def test_gitleaks_REDAKTE_ederek_kosuyor():
    """Depo public, Actions loglari da oyle. Redaksiyonsuz bulgu = sizdirmanin ta kendisi."""
    assert "--redact" in _gitleaks_tarama_komutu()


def test_gitleaks_TUM_gecmisi_tariyor():
    """Iki parca birden gerekli: --log-opts=--all ve sig OLMAYAN klon."""
    assert '--log-opts="--all"' in _gitleaks_tarama_komutu(), "yalnizca HEAD taraniyor olabilir"
    checkout = [
        adim
        for adim in _yaml(AUDIT)["jobs"]["secrets"]["steps"]
        if "checkout" in str(adim.get("uses", ""))
    ]
    assert checkout and checkout[0].get("with", {}).get("fetch-depth") == 0, (
        "sig klon: gitleaks tek commit gorur ve is YESIL yanar"
    )


def test_pip_audit_SURUMU_pinli():
    """Denetim araci 'ne varsa en son' kuruyorsa, kendisi tedarik zinciri deligidir."""
    kurulum = [b for b in _run_bloklari(AUDIT) if "pip install pip-audit" in b]
    assert kurulum, "pip-audit kurulum adimi yok"
    assert all(re.search(r"pip-audit==\d+\.\d+", b) for b in kurulum), "pip-audit pinsiz kuruluyor"


def test_pip_audit_STRICT_kosuyor():
    """--strict olmadan 'atlandi' ile 'temiz' ayni ciktiya benziyor."""
    kosular = [b for b in _run_bloklari(AUDIT) if "pip_audit" in b or "pip-audit -r" in b]
    denetim = [b for b in kosular if "pip install" not in b]
    assert len(denetim) >= 2, "iki denetim adimi bekleniyor (requirements + kurulu ortam)"
    assert all("--strict" in b for b in denetim), "--strict'siz pip-audit kosusu var"


# --- codeql.yml ---------------------------------------------------------------


CODEQL = WF_DIR / "codeql.yml"


def test_codeql_python_analiz_ediyor_ve_SONUC_yaziyor():
    d = _yaml(CODEQL)
    metin = _metin(CODEQL)
    assert "languages: python" in metin
    izinler = d["jobs"]["analyze"]["permissions"]
    assert izinler.get("security-events") == "write", (
        "security-events: write olmadan bulgular Security sekmesine yazilamaz"
    )


def test_zamanlanmis_tarama_DURMUYOR():
    """Bir bagimlilik degismeden de acik hale gelir; push-only tarama bunu kacirir."""
    for wf in (AUDIT, CODEQL):
        d = _yaml(wf)
        # PyYAML `on:` anahtarini True olarak okur (YAML 1.1 booleani).
        tetik = d.get("on", d.get(True))
        assert tetik and "schedule" in tetik, f"{wf.name}: zamanlanmis tarama yok"
