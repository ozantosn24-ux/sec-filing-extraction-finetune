"""Olcum takimi — UC yarismaci ayni cetvelle olculur.

⚠️ Bu dosya, herhangi bir model kosmadan ONCE yazildi. Sebep metodolojik:
sonucu gordukten sonra yazilan metrik, farkinda olmadan cikan sonuca gore
sekillenir ("su alani disarida biraksak daha temiz olur"). Metrik once sabitlenir.

## Girdi

Tahmin dosyasi JSONL, her satir:
    {"accession": "...", "raw": "<modelin URETTIGI HAM METIN>", "latency_s": 1.2}

`raw` bilerek HAM: sema gecerliligi bir METRIK, dolayisiyla eval'in modelin
gercekte ne yazdigini gormesi gerekiyor. Onceden ayristirilmis sozluk alsaydik
"gecersiz JSON uretti" vakasi olcum defterinden dusordu.

## Metrikler ve NEDEN ayri durduklari

1. **Sema gecerliligi** — JSON ayrisiyor mu, 13 anahtar var mi, tipler tutuyor mu.
   Sema ihlali YANLIS DEGERDEN farkli bir hata sinifi. Kucuk fine-tuned modelin
   buyuk prompted modeli yendigi kanonik yer burasi (G13 §3.2).
2. **Alan basina tam eslesme** — dolu alanlarda dogruluk.
3. **DOGRU ABSTENTION — AYRI metrik.** Altin deger null iken null demek.
   Genel dogrulukla toplanirsa gorunmez olur: alanlarin cogu null oldugu icin
   "hep null yaz" diyen bir model yuksek genel skor alir. Ayri durmali ki
   "hicbir sey uretmeyen" model ile "dogru sey ureten" model ayirt edilsin.
4. **UYDURMA orani** — altin null iken deger uretmek. (3)'un aynadaki yuzu degil:
   pay ayni, ama bu sayi projenin bastirmak istedigi DAVRANISI olcer ve tek
   basina raporlanir.
5. **KACIRMA orani** — altin doluyken null demek. Asiri temkinli modelin bedeli.
6. **ZOR VAKA dilimi** — `par_value_usd` ↔ `liquidation_preference_usd`.
   Projenin var olus sebebi; genel ortalamanin icinde erir, ayri raporlanir.
7. **TEK-ORNEK genelleme vakasi** — `offered_unit="unit"` (Energy Transfer LP).
   Egitimde HIC gecmez, yalnizca test'te var. Semayi prompt'tan OKUYAN model
   uretebilir, egitim dagilimini ezberleyen uretemez. Bir vakalik oldugu icin
   yuzde olarak degil ISABET/ISKA olarak raporlanir — 1/1'i "%100 dogruluk"
   diye sunmak olcumu sisirir.

Kullanim:
    python src/evaluate.py preds_regex.jsonl [preds_ft.jsonl ...]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL_DIR = ROOT / "data" / "interim" / "labels"
DEV_FILE = ROOT / "data" / "dev_split.json"

FIELD_ORDER = [
    "series", "coupon_rate_pct", "offered_unit", "depositary_ratio",
    "liquidation_preference_usd", "par_value_usd", "cumulative", "redeemable",
    "convertible", "perpetual", "shares_offered", "dividend_frequency", "is_preliminary",
]

NUMERIC = {"coupon_rate_pct", "liquidation_preference_usd", "par_value_usd"}
INTEGER = {"depositary_ratio", "shares_offered"}
BOOLEAN = {"cumulative", "redeemable", "convertible", "perpetual", "is_preliminary"}
ENUMS = {
    "offered_unit": {"share", "depositary_share", "note", "unit"},
    "dividend_frequency": {"monthly", "quarterly", "semi-annual", "annual"},
}
HARD_CASE_FIELDS = ("par_value_usd", "liquidation_preference_usd")

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def parse_prediction(raw: str) -> tuple[dict | None, list[str]]:
    """(nesne, ihlaller). Ayrisamazsa (None, [...]).

    Markdown citesi TOLERE EDILIR ama ihlal olarak KAYDEDILIR: talimat aciktan
    "no markdown fence" diyor, yani cite bir talimat ihlalidir. Tolere etmemek
    olcumu "bicimlendirme" uzerinden carpitirdi; kaydetmemek ihlali gizlerdi.
    """
    ihlal: list[str] = []
    text = raw.strip()
    if text.startswith("```"):
        ihlal.append("markdown citesi")
        text = _FENCE.sub("", text).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        # Birikmis ihlalleri ATMA. Once atiyordu ve sayac yalan soyluyordu:
        # base 1.5B'nin 36 ciktisinin 36'si da fence'liydi (olculdu), ama
        # ayrisamayan tek kayitta "markdown citesi" dusuruldugu icin histogram
        # 35 diyordu. Sema-gecerli sayisini etkilemiyordu (ayrisamayan kayit
        # zaten gecersiz), ama TESHIS sayaci hatalidir ve arizayi kucuk gosterir.
        return None, ihlal + [f"JSON ayrisamadi: {exc.msg}"]
    if not isinstance(obj, dict):
        return None, ["JSON bir nesne degil"]

    fazla = [k for k in obj if k not in FIELD_ORDER]
    eksik = [k for k in FIELD_ORDER if k not in obj]
    if fazla:
        ihlal.append(f"fazla alan: {fazla}")
    if eksik:
        ihlal.append(f"eksik alan: {eksik}")

    for f in FIELD_ORDER:
        if f not in obj:
            continue
        v = obj[f]
        if v is None:
            if f == "is_preliminary":
                ihlal.append("is_preliminary null olamaz")
            continue
        if f in BOOLEAN and not isinstance(v, bool):
            ihlal.append(f"{f}: bool degil ({type(v).__name__})")
        elif f in INTEGER and (isinstance(v, bool) or not isinstance(v, int)):
            ihlal.append(f"{f}: tam sayi degil ({type(v).__name__})")
        elif f in NUMERIC and (isinstance(v, bool) or not isinstance(v, (int, float))):
            ihlal.append(f"{f}: sayi degil ({type(v).__name__})")
        elif f in ENUMS and v not in ENUMS[f]:
            ihlal.append(f"{f}: enum disi ({v!r})")
        elif f == "series" and not isinstance(v, str):
            ihlal.append(f"series: metin degil ({type(v).__name__})")
    return obj, ihlal


def esit(field: str, gold, pred) -> bool:
    """Sayilarda 25 == 25.0; tipte degil DEGERDE eslesme aranir."""
    if gold is None or pred is None:
        return gold is None and pred is None
    if field in NUMERIC or field in INTEGER:
        try:
            return abs(float(gold) - float(pred)) < 1e-9
        except (TypeError, ValueError):
            return False
    return gold == pred


def dev_accessions() -> set[str]:
    if not DEV_FILE.exists():
        raise SystemExit(f"{DEV_FILE} yok — once `python src/build_sft.py`")
    return set(json.loads(DEV_FILE.read_text(encoding="utf-8"))["accessions"])


def load_gold(split: str = "test") -> dict[str, dict]:
    """Altin etiketler. `dev` bir DOSYA DIZINI DEGIL, train uzerinde bir gorunum.

    Dev train'den sirket bazinda oyuldu ama span/etiket dosyalari yerinde kaldi.
    Bu yuzden dev'in altini train/ altindan accession listesiyle suzuluyor ve
    ayni sebeple `train` de dev'i DISLIYOR: ikisi ayni kaydi sayarsa "egitimde
    gormedigi veri" iddiasi coker.
    """
    src = "train" if split == "dev" else split
    gold = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((LABEL_DIR / src).glob("*.json"))}
    if split == "dev":
        return {k: v for k, v in gold.items() if k in dev_accessions()}
    if split == "train" and DEV_FILE.exists():
        dev = dev_accessions()
        return {k: v for k, v in gold.items() if k not in dev}
    return gold


def score(preds: list[dict], gold: dict[str, dict]) -> dict:
    gecerli = 0
    ihlal_sayaci: dict[str, int] = {}
    alan_dogru: dict[str, int] = {f: 0 for f in FIELD_ORDER}
    alan_toplam: dict[str, int] = {f: 0 for f in FIELD_ORDER}
    abst_dogru = abst_toplam = 0
    uydurma = 0
    kacirma = kacirma_toplam = 0
    zor_dogru = zor_toplam = 0
    tam_kayit = 0
    unit_vakasi: str | None = None
    gecikme: list[float] = []
    degerlendirilen = 0

    for row in preds:
        acc = row["accession"]
        if acc not in gold:
            continue
        degerlendirilen += 1
        g = gold[acc]
        obj, ihlal = parse_prediction(row.get("raw", ""))
        for i in ihlal:
            anahtar = i.split(":")[0]
            ihlal_sayaci[anahtar] = ihlal_sayaci.get(anahtar, 0) + 1
        if obj is not None and not ihlal:
            gecerli += 1
        if row.get("latency_s") is not None:
            gecikme.append(float(row["latency_s"]))

        # Ayrisamayan cikti = tum alanlar YANLIS. Atlamak, bozuk cikti ureten
        # modeli odullendirirdi (paydadan dusurerek).
        p = obj if isinstance(obj, dict) else {}

        kayit_tam = True
        for f in FIELD_ORDER:
            gv, pv = g.get(f), p.get(f)
            dogru = esit(f, gv, pv)
            alan_toplam[f] += 1
            alan_dogru[f] += dogru
            kayit_tam &= dogru
            if gv is None:
                abst_toplam += 1
                abst_dogru += pv is None
                uydurma += pv is not None
            else:
                kacirma_toplam += 1
                kacirma += pv is None
        tam_kayit += kayit_tam

        if all(g.get(f) is not None for f in HARD_CASE_FIELDS):
            for f in HARD_CASE_FIELDS:
                zor_toplam += 1
                zor_dogru += esit(f, g.get(f), p.get(f))

        if g.get("offered_unit") == "unit":
            unit_vakasi = "ISABET" if p.get("offered_unit") == "unit" else f"ISKA ({p.get('offered_unit')!r})"

    return {
        "kayit": degerlendirilen,
        "sema_gecerli": gecerli,
        "sema_gecerli_pct": 100 * gecerli / degerlendirilen if degerlendirilen else 0,
        "ihlaller": ihlal_sayaci,
        "tam_kayit": tam_kayit,
        "tam_kayit_pct": 100 * tam_kayit / degerlendirilen if degerlendirilen else 0,
        "alan": {f: (alan_dogru[f], alan_toplam[f]) for f in FIELD_ORDER},
        "abstention": (abst_dogru, abst_toplam),
        "uydurma": (uydurma, abst_toplam),
        "kacirma": (kacirma, kacirma_toplam),
        "zor_vaka": (zor_dogru, zor_toplam),
        "unit_vakasi": unit_vakasi or "test setinde yok",
        "gecikme_med": sorted(gecikme)[len(gecikme) // 2] if gecikme else None,
    }


def rapor(ad: str, s: dict) -> None:
    def oran(pair):
        d, t = pair
        return f"{d}/{t} ({100*d/t:.1f}%)" if t else "-"

    print(f"\n{'='*66}\n{ad}  —  {s['kayit']} kayit\n{'='*66}")
    print(f"  sema gecerliligi      {s['sema_gecerli']}/{s['kayit']} ({s['sema_gecerli_pct']:.1f}%)")
    if s["ihlaller"]:
        for k, v in sorted(s["ihlaller"].items(), key=lambda x: -x[1]):
            print(f"      ihlal: {k:<28} {v}")
    print(f"  TAM kayit (13/13)     {s['tam_kayit']}/{s['kayit']} ({s['tam_kayit_pct']:.1f}%)")
    print(f"  dogru abstention      {oran(s['abstention'])}   <- altin null iken null")
    print(f"  UYDURMA               {oran(s['uydurma'])}   <- altin null iken deger uretti")
    print(f"  kacirma               {oran(s['kacirma'])}   <- altin dolu iken null dedi")
    # Ayrisamayan cikti TUM alanlari None yapar; bu da abstention'i SERBEST puan
    # haline getirir. Olculdu: adaptorsuz 135M model duz nesir uretti, sema
    # gecerliligi %0 — ve "dogru abstention" %100 cikti. Tek basina alintilanirsa
    # bozuk bir modeli iyi gosterir, o yuzden sayinin YANINDA soyleniyor.
    ayrisamayan = s["ihlaller"].get("JSON ayrisamadi", 0)
    if ayrisamayan:
        print(f"      UYARI: {ayrisamayan} kayit AYRISAMADI -> o kayitlarda tum alanlar "
              f"null sayildi.\n"
              f"         Abstention'i bu haliyle basari diye okumayin: yukaridaki "
              f"kacirma oranina bakin.")
    print(f"  ZOR VAKA (par<->liq)  {oran(s['zor_vaka'])}")
    print(f"  tek-ornek 'unit'      {s['unit_vakasi']}")
    if s["gecikme_med"] is not None:
        print(f"  gecikme (medyan)      {s['gecikme_med']:.2f} sn")
    print("  --- alan basina tam eslesme ---")
    for f, (d, t) in s["alan"].items():
        p = 100 * d / t if t else 0
        print(f"      {f:<28}{d:>3}/{t:<4}{p:>6.1f}% {'#' * int(p/5)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("preds", nargs="+", help="tahmin JSONL dosyalari")
    ap.add_argument("--split", default="test", choices=("train", "dev", "test"),
                    help="altin etiket bolmesi. train = kural GELISTIRME, "
                         "dev = MODEL SECIMI (epoch/lr/checkpoint); "
                         "nihai karsilastirma HER ZAMAN test.")
    ap.add_argument("--json-out", type=Path, help="karsilastirmayi JSON olarak yaz")
    args = ap.parse_args()

    gold = load_gold(args.split)
    if not gold:
        raise SystemExit(f"altin etiket yok: {args.split}")
    uyari = {
        "train": "   UYARI: GELISTIRME kosusu — bu sayilar sonuc DEGILDIR",
        "dev": "   UYARI: SECIM kosusu — burada ayar yapilir, sonuc BURADAN raporlanmaz",
    }
    print(f"altin: {len(gold)} {args.split} kaydi" + uyari.get(args.split, ""))

    hepsi = {}
    for f in args.preds:
        p = Path(f)
        rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        s = score(rows, gold)
        hepsi[p.stem] = s
        rapor(p.stem, s)
        eksik = len(gold) - s["kayit"]
        if eksik:
            print(f"  UYARI: {eksik} test kaydi icin tahmin YOK — kapsam eksik, "
                  f"skorlar bu haliyle karsilastirilamaz")

    if len(hepsi) > 1:
        print(f"\n{'='*66}\nKARSILASTIRMA\n{'='*66}")
        ad_w = max(len(a) for a in hepsi)
        print(f"  {'yarismaci':<{ad_w}}  sema%  tam%  abst%  uydurma%  zor%")
        for a, s in hepsi.items():
            ab = 100 * s["abstention"][0] / s["abstention"][1] if s["abstention"][1] else 0
            uy = 100 * s["uydurma"][0] / s["uydurma"][1] if s["uydurma"][1] else 0
            zo = 100 * s["zor_vaka"][0] / s["zor_vaka"][1] if s["zor_vaka"][1] else 0
            print(f"  {a:<{ad_w}}  {s['sema_gecerli_pct']:>5.1f}  {s['tam_kayit_pct']:>4.1f}  "
                  f"{ab:>5.1f}  {uy:>8.1f}  {zo:>4.1f}")

    if args.json_out:
        args.json_out.write_text(json.dumps(hepsi, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n-> {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
