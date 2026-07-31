"""SFT egitim seti — etiket + span'den `data/processed/sft_{train,test}.jsonl`.

KAYNAK-I HAKIKAT ETIKETTIR. Dongu labels/ uzerinde doner, spans/ uzerinde degil;
boylece etiketi olmayan (cikarilmis ama yeniden uretilmis) bir span sete SIZAMAZ.

## Kararlar

**Hedef = 13 alan, `evidence` YOK.** Kanit blogu etiketlemenin denetim araci;
cikarim hedefi degil. Kapsami esitsiz (alan basina 151/100/99/78/10) — bunun
uzerine egitmek "bazen alintila, bazen alintilama" ogretir. Kanit uretmesi
istenen bir varyant mesru bir ABLASYON'dur, taban kosu degil.

**Abstention kayitlari SETTE.** G13'un altini cizdigi nokta: cikarilirsa model
"bulamayinca uydur" ogrenir. Bu setin en ayirt edici parcasi bunlar.

**Isaretli 12 kayit SETTE (varsayilan).** Bayraklarin 10'u "kanit birebir degil"
turunden ve kanit zaten hedef DEGIL — alan degerlerine dokunmuyorlar. Yine de
`meta.flagged` ile isaretleniyor ve `--exclude-flagged` ile disari alinabiliyor;
karar olcume birakildi, veri sessizce budanmadi.

**Cikti tek satir kompakt JSON.** Girinti token yakar ve tam-eslesme
karsilastirmasini bicime duyarli hale getirir.

**DEV bolmesi train'den OYULUR.** Sebep metodolojik: epoch sayisi, ogrenme orani
ve hangi checkpoint'in alinacagi bir yere BAKILARAK secilir. O yer test olursa
"kural-tabanliyi yendi" iddiasi test uzerinde ayarlanmis demektir ve depo bunu
zaten kural-tabanli icin acikca reddediyor (kurallar train'de gelistirildi, test
BIR KEZ kosuldu). Model secimi icin de ayni cetvel gerekiyor.

Oyma SIRKET bazinda — belge bazinda oyulsa ayni ihraccinin kalip metni hem
egitimde hem secimde gorunur ve dev skoru siser. `split.py` ile AYNI mantik,
ayri tohum.

Kullanim:
    python src/build_sft.py [--exclude-flagged]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from prompt import build_prompt

ROOT = Path(__file__).resolve().parent.parent
LABEL_DIR = ROOT / "data" / "interim" / "labels"
SPAN_DIR = ROOT / "data" / "interim" / "spans"
MANIFEST = ROOT / "data" / "interim" / "manifest.json"
# manifest'te olmayan accession'lar icin git'te TAKIP EDILEN ek eslesme.
# data/interim/ .gitignore'da oldugu icin kaynak veri geri getirilemiyor;
# bu dosya olmadan sirket-bazli bolme dogrulanamaz.
EXTRA_KEYS = ROOT / "data" / "company_keys_extra.json"
FLAG_FILE = ROOT / "data" / "interim" / "label_flags.json"
OUT_DIR = ROOT / "data" / "processed"
# Oyulan dev bolmesi git'te TAKIP EDILIR. `data/interim/` versiyonlanmadigi icin
# bu dosya olmadan "hangi kayitlarda secim yapildi" sorusu sonradan
# cevaplanamaz — yani olcum tekrar-uretilebilir olmaz.
DEV_FILE = ROOT / "data" / "dev_split.json"

DEV_SEED = "edgar-extract-dev-v1"
DEV_FRACTION = 0.20
# Dev'in ISE YARAMASI icin iki dilimi de tasimasi gerekir: abstention (altin
# deger null) ve zor vaka (par ↔ liq). Bunlar olmadan dev "JSON sekli dogru mu"
# disinda bir sey soyleyemez, oysa secim tam da bu davranislar icin yapilacak.
# Kisit ONCEDEN yaziliyor — tohumu begenene kadar degistirmek ayarlamaktir.
DEV_MIN_SLICE = 4

FIELD_ORDER = [
    "series", "coupon_rate_pct", "offered_unit", "depositary_ratio",
    "liquidation_preference_usd", "par_value_usd", "cumulative", "redeemable",
    "convertible", "perpetual", "shares_offered", "dividend_frequency", "is_preliminary",
]


def target_json(label: dict) -> str:
    """Kanonik hedef dizgi: sabit anahtar sirasi, kompakt ayirici."""
    obj = {f: label.get(f) for f in FIELD_ORDER}
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def company_keys() -> dict[str, str]:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    keys = {r["accession"]: r["company_key"] for split in ("train", "test") for r in m[split]}
    if EXTRA_KEYS.exists():
        extra = json.loads(EXTRA_KEYS.read_text(encoding="utf-8"))
        keys.update({e["accession"]: e["company_key"] for e in extra["keys"]})
    return keys


def carve_dev(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """train satirlarini (train, dev) diye ayirir — SIRKET bazinda, deterministik.

    Sirketler sabit tohumla hash'lenip siralanir, hedef belge sayisina VE iki
    dilim kotasina birlikte ulasilana kadar sirasiyla dev'e alinir. Rastgelelik
    yok: ayni girdi ayni bolmeyi verir.

    Kota dongunun icinde cunku dilimler sirketlere esit dagilmiyor — yalniz
    belge sayisina bakan bir oyma, abstention'i sifir olan bir dev uretebilir
    ve o dev, secimin sorulacagi sorulari cevaplayamaz.
    """
    by_company: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_company[r["company_key"]].append(r)

    sira = sorted(by_company, key=lambda c: hashlib.sha256(f"{DEV_SEED}:{c}".encode()).hexdigest())
    hedef = round(len(rows) * DEV_FRACTION)

    dev_companies: list[str] = []
    n = abst = zor = 0
    for c in sira:
        if n >= hedef and abst >= DEV_MIN_SLICE and zor >= DEV_MIN_SLICE:
            break
        dev_companies.append(c)
        n += len(by_company[c])
        abst += sum(1 for r in by_company[c] if r["meta"]["abstention"])
        zor += sum(1 for r in by_company[c] if r["meta"]["hard_case_par_vs_liq"])

    secili = set(dev_companies)
    if abst < DEV_MIN_SLICE or zor < DEV_MIN_SLICE:
        raise SystemExit(
            f"dev dilim kotasi tutmadi (abstention={abst}, zor_vaka={zor}, "
            f"gereken {DEV_MIN_SLICE}) — train seti bu kotayi tasiyamiyor.")

    dev = [r for r in rows if r["company_key"] in secili]
    kalan = [r for r in rows if r["company_key"] not in secili]
    for r in dev:
        r["split"] = "dev"
        # Kaynak dosyalar TASINMAZ: span ve etiket `train/` altinda kalir, dev
        # onlarin uzerine bir GORUNUM. Tasimak manifest'i ve tekrar-uretimi bozardi.
        r["source_split"] = "train"
    return kalan, dev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude-flagged", action="store_true",
                    help="isaretli kayitlari sete alma (varsayilan: al, meta'da isaretle)")
    ap.add_argument("--no-dev", action="store_true",
                    help="dev bolmesini oyma (train'in tamami egitime gider). "
                         "Secim yapilacaksa KULLANMAYIN — secim yeri kalmaz.")
    args = ap.parse_args()

    flags = json.loads(FLAG_FILE.read_text(encoding="utf-8")) if FLAG_FILE.exists() else {}
    ckeys = company_keys()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stats: dict[str, dict] = {}
    unknown_company: list[str] = []
    collected: dict[str, list[dict]] = {}
    atlanan: dict[str, int] = {}

    for split in ("train", "test"):
        rows = []
        skipped_flagged = 0
        for p in sorted((LABEL_DIR / split).glob("*.json")):
            acc = p.stem
            if args.exclude_flagged and acc in flags:
                skipped_flagged += 1
                continue

            span_file = SPAN_DIR / split / f"{acc}.txt"
            if not span_file.exists():
                raise SystemExit(f"span YOK: {split}/{acc} — once clean_dataset.py kosun")

            label = json.loads(p.read_text(encoding="utf-8"))
            missing = [f for f in FIELD_ORDER if f not in label]
            if missing:
                raise SystemExit(f"{split}/{acc}: eksik alan {missing} — normalize_labels.py kosun")

            span = span_file.read_text(encoding="utf-8")
            prompt = build_prompt(span)
            completion = target_json(label)

            filled = sum(1 for f in FIELD_ORDER if f != "is_preliminary" and label.get(f) is not None)

            # Sirketi bilinmeyen kayit SESSIZCE gecmez. Ilk surumde bilinmeyenler
            # "?" oluyordu; "?" iki bolmede birden gorunup SAHTE bir ortusme
            # uretti — ve tek bolmede kalsaydi gercek bir provenance bosluguna
            # ortusme-temiz suslemesi yapacakti. Bolme garantisi sirket kimligine
            # dayaniyor; kimlik yoksa garanti de yok.
            ck = ckeys.get(acc)
            if ck is None:
                unknown_company.append(f"{split}/{acc}")
                continue

            rows.append({
                "accession": acc,
                "split": split,
                "source_split": split,
                "company_key": ck,
                # Iki bicim birden: sohbet formati ve duz prompt/completion. TRL'in
                # hangi girisi bekledigi surumle degisiyor (G13: surum-ozgu imzalari
                # uygulama aninda dogrula) — egitim scripti ikisinden birini secer,
                # veri yeniden uretilmez.
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": completion},
                ],
                "prompt": prompt,
                "completion": completion,
                "meta": {
                    "is_preliminary": bool(label.get("is_preliminary")),
                    "n_filled": filled,
                    # Abstention dilimi: fiyatlama alanlarinin dogru cevabi null.
                    "abstention": bool(label.get("is_preliminary")),
                    # ZOR VAKA: par ve liq ayni belgede birlikte dolu — projenin
                    # var olus sebebi olan ayrim. Adim ③ bunu AYRI dilim raporlar.
                    "hard_case_par_vs_liq": (label.get("par_value_usd") is not None
                                             and label.get("liquidation_preference_usd") is not None),
                    "offered_unit": label.get("offered_unit"),
                    "flagged": acc in flags,
                    "span_chars": len(span),
                    "prompt_chars": len(prompt),
                },
            })

        collected[split] = rows
        atlanan[split] = skipped_flagged

    if unknown_company:
        print(f"SIRKETI BILINMEYEN {len(unknown_company)} kayit — sete ALINMADI:")
        for u in unknown_company:
            print(f"   {u}")
        print("   -> data/company_keys_extra.json'a kanitiyla ekleyin (span'deki borsa sembolu)")
        return 1

    if args.no_dev:
        print("UYARI --no-dev: dev bolmesi OYULMADI. Epoch/lr/checkpoint secimi "
              "yapilacaksa yapilacak yer test olur ve karsilastirma kirlenir.\n")
        DEV_FILE.unlink(missing_ok=True)
        (OUT_DIR / "sft_dev.jsonl").unlink(missing_ok=True)
        siralar = {"train": collected["train"], "test": collected["test"]}
    else:
        kalan, dev = carve_dev(collected["train"])
        siralar = {"train": kalan, "dev": dev, "test": collected["test"]}
        DEV_FILE.write_text(json.dumps({
            "seed": DEV_SEED,
            "fraction": DEV_FRACTION,
            "min_slice": DEV_MIN_SLICE,
            "not": "train'den SIRKET bazinda oyuldu; span/etiket dosyalari train/ altinda kalir",
            "companies": sorted({r["company_key"] for r in dev}),
            "accessions": sorted(r["accession"] for r in dev),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    seen: dict[str, set[str]] = {}
    for split, rows in siralar.items():
        out = OUT_DIR / f"sft_{split}.jsonl"
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        seen[split] = {r["company_key"] for r in rows}
        stats[split] = {
            "kayit": len(rows),
            "sirket": len(seen[split]),
            "abstention": sum(1 for r in rows if r["meta"]["abstention"]),
            "zor_vaka": sum(1 for r in rows if r["meta"]["hard_case_par_vs_liq"]),
            "isaretli": sum(1 for r in rows if r["meta"]["flagged"]),
            # dev train'den oyuldu -> atlanan isaretli sayisi train'in hanesinde.
            "atlanan_isaretli": atlanan[rows[0]["source_split"]] if rows else 0,
            "en_uzun_prompt_karakter": max((r["meta"]["prompt_chars"] for r in rows), default=0),
            "dosya": str(out.relative_to(ROOT)),
        }

    for split, s in stats.items():
        print(f"{split:<6} kayit={s['kayit']:<4} sirket={s['sirket']:<4} "
              f"abstention={s['abstention']:<3} zor_vaka={s['zor_vaka']:<3} "
              f"isaretli={s['isaretli']}")
        print(f"       -> {s['dosya']}  (en uzun prompt {s['en_uzun_prompt_karakter']:,} karakter)")

    # Her CIFT icin ayri kontrol: train↔test tarihsel garanti, ama train↔dev
    # olmadan dev bir secim araci degil sadece ikinci bir egitim seti olurdu.
    sizinti = False
    for a, b in (("train", "test"), ("train", "dev"), ("dev", "test")):
        if a not in seen or b not in seen:
            continue
        ortak = seen[a] & seen[b]
        print(f"\nSIRKET ORTUSMESI {a}<->{b}: {len(ortak)}  "
              f"{'<- SIZINTI!' if ortak else '(temiz)'}")
        for c in sorted(ortak):
            print(f"   {c}")
        sizinti |= bool(ortak)
    if sizinti:
        return 1

    print("\nNOT: token sayisi TAHMIN EDILMEDI. Gercek tokenizer ile olculmeli — "
          "egitim scripti sec_len'i olctugu degere gore ayarlar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
