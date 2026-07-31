# Çıkarım şeması — imtiyazlı hisse ihracı (424B5)

**Kaynak:** şema masa başında değil, **indirilen gerçek belgelerden** türetildi (2026-07-31).
Örnekler: NexPoint `0001437749-25-030192` · Realty Income `0001104659-12-019841` ·
AGNC `0001423689-25-000088`.

**Görev:** yoğun hukuki metinden katı şemaya yapılandırılmış alan çıkarma.
Bu, PrefEdge'in kural-tabanlı parser'ının **yapamayıp bıraktığı** iş —
`edgar_parser.py` içinde aynen yazıyor: *"Coupon/par/issue_size require fetching the full
prospectus — left as None for now."*

---

## Alanlar (hepsi gerçek belgede GÖZLEMLENDİ)

| alan | tip | örnek | nereden |
|---|---|---|---|
| `issuer_name` | str | `NexPoint Real Estate Finance, Inc.` | kapak |
| `cik` | str | `1443089` | dosyalama metadata |
| `series` | str \| null | `B`, `F` | `Series B` / `Class F` |
| `coupon_rate_pct` | float \| null | `9.00`, `6.625` | başlıktaki `9.00%` |
| `liquidation_preference_usd` | float \| null | `25.00` | `Liquidation Preference $25.00 per share` |
| `par_value_usd` | float \| null | `0.01` | `par value $0.01 per share` |
| `cumulative` | bool \| null | `true` | başlıkta `Cumulative` geçer |
| `redeemable` | bool \| null | `true` | başlıkta `Redeemable` geçer |
| `convertible` | bool \| null | `true` | `issuable upon conversion` + `share cap` |
| `shares_offered` | int \| null | `3482858` | `Maximum of 3,482,858 Shares` |
| `overallotment_shares` | int \| null | `1950000` | `may be purchased by the underwriters upon the exercise of the ... overallotment option` |
| `aggregate_offering_usd` | float \| null | `373750000` | ücret tablosu `Proposed Maximum Aggregate Offering Price` |
| `dividend_frequency` | enum \| null | `monthly`, `quarterly` | `Monthly Income ... Preferred Stock` |

`null` = belgede yok. **Uydurma yok**; model bulamadığında `null` dönmeli ve eval bunu ödüllendirmeli.

## ⭐ ZOR VAKA — bu projenin var oluş sebebi

**`par_value_usd` ≠ `liquidation_preference_usd`.**

Realty Income Class F belgesinde ikisi de aynı cümlede geçiyor:

> `6.625% Monthly Income Class F Cumulative Redeemable Preferred Stock, **par value $0.01 per share**`
> … aynı tabloda `Proposed Maximum Offering Price Per Security: **$25.00**`

Naif bir çıkarıcı (ve dikkatsiz bir etiketçi) `par` kelimesini görüp **0,01**'i alır.
Oysa getiri hesabında anlamlı olan **25,00**'dır. Kupon × 25 = yıllık temettü;
kupon × 0,01 saçmadır. Bu ayrım **alan bilgisi** gerektirir, kelime eşleştirmesi çözmez.

⇒ Bu, "küçük fine-tuned model, büyük prompted modeli yener mi" sorusunun **ölçüleceği yer**.
Eval'de ayrı bir zor-vaka dilimi olarak raporlanacak.

## Diğer ölçülmüş tuzaklar

1. **`dividend_frequency` varsayılamaz.** Çoğu imtiyazlı çeyreklik öder ama Realty Income
   Class F **aylık** (`Monthly Income`). "Quarterly" varsayan çıkarıcı sessizce yanılır.
2. **`shares_offered` overallotment içerebilir.** Realty Income'da 14.950.000'in
   1.950.000'i overallotment. İkisini ayırmayan bir alan yanlış ihraç büyüklüğü verir.
3. **Belge tipi karışık.** `424B5` kutusunda asıl prospektüsle kısa tadil belgeleri bir arada.
   Ölçüm: 2.096 / 3.549 / 4.117 / 4.688 karakter (kısa tadil) ↔ 36.038 / 45.937 / 395.318
   (asıl belge). **20.000 karakter eşiği** temiz ayırıyor.
   ⚠️ Ama eşik "tadil ↔ orijinal"i ayırmaz, "önemsiz ↔ esaslı"yı ayırır: NexPoint belgesi
   *Amendment No. 1* olduğu hâlde 45.937 karakter ve tüm terimleri taşıyor.

## Doğrulanmamış — eklenmeden ÖNCE gözlemlenmeli

Bu alanlar imtiyazlı hisselerde yaygındır ama **bu üç belgede görmedim**, o yüzden şemada YOK:
`call_date` (ilk çağrı tarihi) · `fixed_to_floating` ve reset marjı · `perpetual` vs vade ·
`ticker` (imtiyazlı sembolü) · `use_of_proceeds`.
Daha geniş örneklem çekildiğinde gözlemlenirse eklenecek — tersi değil.
