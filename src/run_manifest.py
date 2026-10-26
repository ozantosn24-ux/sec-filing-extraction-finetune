"""Kosu manifesti — bir olcumun HANGI girdilerle uretildigini kayda gecirir.

`src/pins.py` modelin hangi revision'a sabitlendigini soyler; ama bir kosunun o pini
GERCEKTEN kullandigini, hangi dtype/kuantizasyon/uretim ayariyla kostugunu ve hangi
veriye baktigini soylemez. Manifest bunu kosunun KENDISINDEN yazar (predict.py ve
train_lora.py sonunda), elle doldurulan bir not olarak degil.

Kurucu (`build_run_manifest`) bilerek torch/transformers/peft IMPORT ETMEZ: duz sozluk
alir, duz sozluk dondurur. Boylece CPU'da, agir bagimlilik olmadan test edilir. Cagiran
taraf (`predict.py`, `train_lora.py`) kendi nesnelerinden (`LoraConfig.to_dict()`,
`BitsAndBytesConfig.to_dict()`) sozlugu uretip verir.

⚠️ Bu dosya yazildiginda HICBIR kosu manifest uretmemisti: yayinlanan sonuclar
(2026-08) bu mekanizmadan ONCE olculdu, yani onlarin manifesti YOKTUR. Manifest
yalnizca bundan sonraki kosulari kapsar; geriye donuk uydurulmaz.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
MANIFEST_PATH = RESULTS / "run_manifest.json"
DATA_MANIFEST = ROOT / "data" / "interim" / "manifest.json"
SCHEMA_VERSION = 1


def _jsonable(obj):
    """Kume -> sirali liste (peft `target_modules`'u kume yapar), digerleri str'e."""
    if isinstance(obj, (set, frozenset)):
        return sorted(_jsonable(x) for x in obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    return str(obj)  # torch.dtype, Path, enum ...


def canonical_sha256(obj) -> str:
    """Anahtar sirasindan ve kume sirasindan bagimsiz parmak izi."""
    blob = json.dumps(_jsonable(obj), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str | None:
    """Dosya yoksa None — 'hash yok' ile 'bos hash' karismasin."""
    path = Path(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_run_manifest(*, kind: str, model_id: str, base_revision: str | None,
                       tokenizer_revision: str | None, dtype, bnb_config: dict | None,
                       generation_config: dict | None, peft_config: dict | None,
                       data_manifest_sha256: str | None, extra: dict | None = None) -> dict:
    """Tek kosunun manifesti. Saf fonksiyon: dosya/ag/GPU'ya dokunmaz.

    `base_revision=None` pinsiz kosu demektir ve OLDUGU GIBI yazilir; manifest bunu
    gizlemez (`pinned: false`), cunku pinsiz kosu tekrar uretilemez.
    """
    if kind not in ("train", "predict"):
        raise ValueError(f"kind 'train' ya da 'predict' olmali, geldi: {kind!r}")
    peft = _jsonable(peft_config) if peft_config is not None else None
    m = {
        "kind": kind,
        "model_id": model_id,
        "base_revision": base_revision,
        "tokenizer_revision": tokenizer_revision,
        "pinned": bool(base_revision) and bool(tokenizer_revision),
        "dtype": str(dtype),
        "bnb_config": _jsonable(bnb_config) if bnb_config is not None else None,
        "generation_config": (_jsonable(generation_config)
                              if generation_config is not None else None),
        "peft_config": peft,
        "peft_config_sha256": canonical_sha256(peft) if peft is not None else None,
        "data_manifest_sha256": data_manifest_sha256,
    }
    if extra:
        m.update(_jsonable(extra))
    return m


def write_run_manifest(entry: dict, key: str, path: Path | None = None) -> Path:
    """`entry`'yi dosyadaki `runs[key]` altina yazar; diger kosulari EZMEZ.

    Anahtar: egitim icin 'train', tahmin icin cikti dosyasinin adi. Ayni anahtarla
    ikinci kosu oncekinin ustune yazar (tekrar-kosu = en son hali).
    """
    path = Path(path) if path else MANIFEST_PATH
    doc = {"schema_version": SCHEMA_VERSION, "runs": {}}
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.setdefault("runs", {})
    doc["runs"][key] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    return path
