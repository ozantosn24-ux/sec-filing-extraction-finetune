"""Cikarim talimati — TEK kaynak.

Adim ②'nin egitim promptu ile adim ③'un "prompted buyuk model" yarismacisi AYNI
talimati kullanmak ZORUNDA. Ayri yerlerde tutulursa biri gelisir, digeri bayatlar
ve karsilastirma sessizce yalan soyler: kazanan model degil, daha iyi yazilmis
prompt olur. Bu yuzden tek modul.

Talimat INGILIZCE: korpus Ingilizce hukuki metin, model Ingilizce ustunde egitildi.
(Repo dokumantasyonu Turkce; MODELE giden metin ayri bir sey.)

Kurallar LABELING.md'deki OLCULMUS tuzaklardan turetildi — susleme degil, her biri
gercek bir hata turunu karsiliyor.
"""

from __future__ import annotations

import re

# GORUNMEZ KARAKTER TEMIZLIGI — ders #4'un yeni kiligi.
# Olculdu (2026-07-31): span'lerde 1.937 adet U+200B ZERO WIDTH SPACE, 41/160 dosyada.
# Hicbiri rakamin ICINDE degil (D|D = 0), hepsi iki bosluk ARASINDA: "per<sp><ZWSP><sp>share".
# Zararsiz gorunur, degil:
#   * `per share` arayan bir regex TUTMAZ (arada fazladan karakter var),
#   * `\s+` de TUTMAZ — U+200B kategorisi Cf (format), bosluk DEGIL.
# Yani adim ③'un kural-tabanli yarismacisini sessizce sakat birakirdi.
# Temizlik TEK yerde, build_prompt icinde: fine-tuned model, prompted model ve regex
# baseline AYNI metni gorur. Depodaki span dosyalari DEGISMEZ — onlar olculmus ham
# artifact ve validate_labels.py kanit kontrolunu onlarin uzerinde kosuyor.
_INVISIBLE = re.compile(r"[​‌‍﻿]")
_RUN_OF_SPACES = re.compile(r"[ \t]{2,}")


def normalize_span(span: str) -> str:
    """Gorunmez karakterleri dusur, olusan cift bosluklari tekle. Satir yapisi KORUNUR
    (tablo duzeni anlam tasiyor, \\s+ ile ezilmez)."""
    return _RUN_OF_SPACES.sub(" ", _INVISIBLE.sub("", span))


# Sema, tipler ve enum'lar. Model bunu OKUYUP uyacak; egitim dagilimini ezberleyip
# uymayan model ile arasindaki fark adim ③'te olculuyor (ornegin "unit" degeri
# egitimde HIC gecmiyor, yalnizca test'te var).
INSTRUCTION = """\
You extract structured data from the cover page of a U.S. SEC Form 424B5 \
preferred-securities prospectus.

Return ONE JSON object with exactly these 13 keys, in this order:

  series                      string | null   e.g. "B", "F", "UU"
  coupon_rate_pct             number | null   e.g. 6.625  (percent, not a fraction)
  offered_unit                "share" | "depositary_share" | "note" | "unit" | null
  depositary_ratio            integer | null  preferred shares per depositary share, e.g. 1000
  liquidation_preference_usd  number | null   PER OFFERED UNIT, e.g. 25.00
  par_value_usd               number | null   legal par, e.g. 0.01
  cumulative                  true | false | null
  redeemable                  true | false | null
  convertible                 true | false | null
  perpetual                   true | false | null
  shares_offered              integer | null  base offering, excluding overallotment
  dividend_frequency          "monthly" | "quarterly" | "semi-annual" | "annual" | null
  is_preliminary              true | false

Rules:

1. If a value is not stated in the text, output null. Never infer, never guess, \
never use outside knowledge. A wrong number is far worse than null.
2. par_value_usd is NOT liquidation_preference_usd. Both can appear in one sentence: \
"... Preferred Stock, par value $0.01 per share" with an offering price of $25.00 \
means par_value_usd=0.01 and liquidation_preference_usd=25.00. If the words \
"liquidation preference" never appear, the per-share offering price is the \
liquidation preference. If neither is stated, both are null.
3. shares_offered and liquidation_preference_usd must refer to THE SAME unit. \
For "24,000,000 Depositary Shares, each representing a 1/1,000th interest in a share \
of Series K Preferred Stock", the offered unit is the depositary share: \
offered_unit="depositary_share", depositary_ratio=1000, shares_offered=24000000, \
liquidation_preference_usd=25.00 (per depositary share) - NOT 25000. Prefer the \
per-offered-unit price even when the text states the larger per-share amount first.
4. A boolean is false ONLY if the text explicitly negates it ("Non-Cumulative" -> \
cumulative=false). Silence means null, not false.
5. Never assume dividend_frequency. "Monthly Income ... Preferred Stock" -> "monthly". \
If the text does not say, output null.
6. "no par value" / "without par value" -> par_value_usd=null, not 0.
7. Preliminary prospectuses leave priced fields blank ("  % Series A ..."). Set \
is_preliminary=true and those fields null - but still fill fields the text does state. \
"Preliminary" does not mean everything is null.
8. Output only the JSON object. No explanation, no markdown fence.

Text:
"""


def build_prompt(span: str) -> str:
    """Talimat + temizlenmis span. Egitimde de eval'de de kullanilan TEK giris bicimi."""
    return INSTRUCTION + normalize_span(span).strip()
