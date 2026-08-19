"""Cikti sozlesmesinin JSON Schema hali — ELLE yazilmadi, SKORLAYICIDAN turetildi.

Neden turetiliyor: constrained decoding, modeli bir sema ile SINIRLAR; olcum ise
`evaluate.parse_prediction` ile skorlar. Bu ikisi elle ayri ayri yazilirsa
sessizce ayrisirlar ve "kisitli uretim sema gecerliligini %100 yapmadi" gibi bir
sonuc, modelin degil IKI SEMANIN farkindan gelir. Tek kaynak: evaluate.py.

Sozlesmenin skorlayicidaki karsiligi:
  * 13 alan, hepsi ZORUNLU (eksik alan bir ihlaldir), fazla alan YASAK
  * `is_preliminary` disinda her alan null OLABILIR
  * `is_preliminary` bool ve null OLAMAZ
  * iki enum alani kapali liste
  * iki alan tam sayi, uc alan sayi, `series` metin
"""

from __future__ import annotations

from evaluate import BOOLEAN, ENUMS, FIELD_ORDER, INTEGER, NUMERIC


def _alan_semasi(alan: str) -> dict:
    """Tek alanin semasi. `is_preliminary` disinda hepsi null kabul eder."""
    if alan in ENUMS:
        temel: dict = {"enum": sorted(ENUMS[alan])}
    elif alan in BOOLEAN:
        temel = {"type": "boolean"}
    elif alan in INTEGER:
        temel = {"type": "integer"}
    elif alan in NUMERIC:
        temel = {"type": "number"}
    else:
        temel = {"type": "string"}

    if alan == "is_preliminary":
        # Skorlayici bunu ACIKTAN yasakliyor ("is_preliminary null olamaz"):
        # belge on prospektus mu degil mi, metinden her zaman okunabilir.
        return temel
    # Geri kalan her alanda null MESRU bir cevap ve projenin can damari:
    # "metinde yoksa null". Null'i semadan cikarmak, kisitli uretimi UYDURMAYA
    # zorlardi — olcmek istedigimiz seyin tam tersi.
    if "enum" in temel:
        return {"enum": [*temel["enum"], None]}
    return {"type": [temel["type"], "null"]}


def cikti_semasi() -> dict:
    """13 alanli, kapali, tum alanlari zorunlu JSON Schema."""
    return {
        "type": "object",
        "properties": {alan: _alan_semasi(alan) for alan in FIELD_ORDER},
        "required": list(FIELD_ORDER),
        "additionalProperties": False,
    }
