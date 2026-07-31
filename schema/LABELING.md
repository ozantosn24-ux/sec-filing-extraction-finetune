# Etiketleme talimatı

Girdi: `data/interim/spans/{train,test}/<accession>.txt` — 424B5 prospektüsünden
konumlandırılmış kapak penceresi (~6.000 karakter).
Çıktı: `data/interim/labels/{train,test}/<accession>.json` — aşağıdaki şema.

## Çıktı şeması

```json
{
  "issuer_name": "NexPoint Real Estate Finance, Inc.",
  "series": "B",
  "coupon_rate_pct": 9.00,
  "offered_unit": "share",
  "depositary_ratio": null,
  "liquidation_preference_usd": 25.00,
  "par_value_usd": 0.01,
  "cumulative": true,
  "redeemable": true,
  "convertible": null,
  "perpetual": true,
  "shares_offered": 3482858,
  "dividend_frequency": "quarterly",
  "is_preliminary": false,
  "evidence": {
    "coupon_rate_pct": "9.00% Series B Cumulative Redeemable Preferred Stock",
    "liquidation_preference_usd": "Liquidation Preference $25.00 per share"
  }
}
```

## Kesin kurallar

1. **Metinde YOKSA `null` yaz. ASLA tahmin etme, çıkarım yapma, dünya bilgisi kullanma.**
   Yanlış bir sayı, `null`'dan çok daha zararlı.
2. `evidence` bloğuna, doldurduğun **her sayısal alan için** metinden **birebir alıntı**
   koy (kısa, tek satır). Alıntıyı bulamıyorsan o alan `null` olmalı.
3. Sayılar sayı olarak yazılır: `9.00` (`"9.00%"` değil), `3482858` (`"3,482,858"` değil).
4. Bool alanlar yalnız `true`/`false`/`null`.

## ⚠️ ZOR VAKALAR — en sık hata burada

### A) `par_value_usd` ≠ `liquidation_preference_usd`

Aynı cümlede ikisi birden geçebilir:

> `6.625% Monthly Income Class F Cumulative Redeemable Preferred Stock, **par value $0.01 per share**`
> … tabloda `Proposed Maximum Offering Price Per Security: **$25.00**`

- `par_value_usd` = **0.01** (hukuki nominal değer, genelde 0.01 veya 0.001)
- `liquidation_preference_usd` = **25.00** (tasfiye tercihi; getiri hesabında anlamlı olan bu)

**`Liquidation Preference` ifadesi geçmeyebilir.** O zaman `$25.00` / `$1,000` gibi
"offering price per share/security" değeri tasfiye tercihidir — imtiyazlı hisselerde
ihraç fiyatı tasfiye tercihine eşittir. Bunu **yalnız** metinde böyle bir fiyat varsa yaz.
İkisi de yoksa ikisi de `null`.

### B) `dividend_frequency` VARSAYILMAZ

Çoğu imtiyazlı çeyreklik öder ama hepsi değil: `Monthly Income ... Preferred Stock` = `monthly`.
İzin verilen değerler: `"monthly"`, `"quarterly"`, `"semi-annual"`, `"annual"`, `null`.
Metin açıkça söylemiyorsa **`null`** — "genelde çeyrekliktir" diye yazma.

### C) `shares_offered` overallotment içerebilir

> `14,950,000` … `Includes 1,950,000 shares … underwriters' overallotment option`

`shares_offered` = **taban ihraç** = 14.950.000 − 1.950.000 = **13.000.000**.
Metin ayrımı yapmıyorsa gördüğün toplamı yaz.

### D) Ön prospektüs → sayısal alanlar `null`

Fiyatlama öncesi belgelerde rakamlar boş bırakılır:

> `Shares  % Series A Cumulative Redeemable Preferred Stock`
> `a share of our  % Fixed Rate Reset Non-Cumulative Perpetual Preferred Stock, Series B`

Bu durumda `is_preliminary: true` ve `coupon_rate_pct: null`, `shares_offered: null`.
Ama `series`, `cumulative`, `perpetual` gibi **metinde açıkça yazan** alanlar yine doldurulur.
Bu kayıtlar veri setinin **abstention** dilimidir; doğru cevap `null`'dır.

### 🔴 F) DEPOSITARY YAPI — BİRİM EŞLEŞTİRMESİ (en pahalı hata)

Ölçüldü: ilk etiketleme turunda **24/27 depositary kaydı bozuktu**. Örnek:
`12.000.000 depositary share × $25.000 = 300 milyar dolar`. AGNC 300 **milyon** topladı.
Sebep: `shares_offered` depositary hisseden, `liquidation_preference_usd` alttaki
imtiyazlı hisseden alınmıştı. **Birimler karışınca 1000 kat sapma.**

**Kural: `shares_offered` ve `liquidation_preference_usd` AYNI birime ait olmalı.**

Kapak sayfası neyi satıyorsa o birim esastır:

> `24,000,000 Depositary Shares, each representing a 1/1,000th interest in a share of
> 7.375% Fixed-Rate Reset Non-Cumulative Preferred Stock, Series K`

- `offered_unit`: `"depositary_share"`
- `depositary_ratio`: `1000` (bir imtiyazlı hisse = 1000 depositary share)
- `shares_offered`: `24000000` (depositary hisse adedi)
- `liquidation_preference_usd`: **`25.00`** (depositary hisse başına) — `25000` DEĞİL

Depositary yapı yoksa: `offered_unit: "share"`, `depositary_ratio: null`.

**Kendi kendini kontrol et:** `shares_offered × liquidation_preference_usd` ihracın
toplam büyüklüğünü vermeli ve bu **10 milyon – 5 milyar dolar** aralığında olmalı.
Milyar üstü çıkıyorsa birimleri karıştırmışsındır.

### 🔴 G) BOOL ALANLAR — sessizlikten `false` ÇIKARMA

Ölçüldü: `cumulative` 43 kez `false` etiketlendi çünkü başlıkta açıkça **"Non-Cumulative"**
yazıyor. `convertible` ise 87 belgenin yalnız **1'inde** açıkça olumsuzlanıyor.

**Kural: bir bool yalnızca metin AÇIKÇA olumsuzluyorsa `false` olur. Sessizlik → `null`.**

- `Non-Cumulative` yazıyor → `cumulative: false` ✅
- `convertible` kelimesi hiç geçmiyor → `convertible: null` ✅ (`false` DEĞİL)

Sebep: etiket, modele verilen **metinde ne olduğunu** tanımlar, menkul kıymetin gerçeğini
değil. Sessizlikten `false` üretirsek modele "girdide olmayan şeyi tahmin et" öğretmiş
oluruz — tam da engellemeye çalıştığımız davranış.

### H) `no par value`

Metin *"no par value"* / *"without par value"* diyorsa `par_value_usd: null`.
Bu bilinçli karardır: alan bir **dolar tutarı**dır, "par değeri yok" o tutarın
var olmaması demektir. `0.00` yazma — o, "par değeri sıfır dolar" anlamına gelir ve
farklı bir iddiadır. (Ölçüm: 8/87 belge, tüm etiketçiler bağımsız olarak `null` seçti.)

### E) Terimlerin okunuşu

- `Cumulative` → `cumulative: true` · `Non-Cumulative` → `false`
- `Redeemable` → `redeemable: true`
- `Perpetual` → `perpetual: true` (vade yok). Vade tarihi yazıyorsa `false`.
- `Convertible` ya da `issuable upon conversion` → `convertible: true`
- Depositary share yapısı (`1/1000th interest in a share of ...`): `liquidation_preference_usd`
  **temel imtiyazlı hissenin** tercihidir (ör. $25.000), depositary share'in değil ($25).
  Hangisini yazdığını `evidence` ile göster.

## Kalite

Emin olamadığın alanı `null` bırak ve `evidence`'a not düşme. Bu veri seti bir
**ölçüm** için kuruluyor; uydurulmuş bir etiket, ölçümün tamamını geçersiz kılar.
