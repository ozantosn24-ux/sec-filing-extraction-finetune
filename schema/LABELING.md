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

Bu durumda `is_preliminary: true` ve boş bırakılan alanlar `null`.
Ama `series`, `cumulative`, `perpetual` gibi **metinde açıkça yazan** alanlar yine doldurulur.
Bu kayıtlar veri setinin **abstention** dilimidir; boş bırakılanların doğru cevabı `null`'dır.

⚠️ **"Ön prospektüs ⇒ her şey null" DEĞİL.** Ölçüldü: Albemarle (`0001193125-24-057936`)
ön prospektüs olmasına rağmen kapakta `35,000,000 depositary shares` açıkça yazıyor;
Microchip'te de `27,000,000` var. **Alan alan metne bak** — yalnız gerçekten boş
bırakılmış olanı `null` yap. Fiyatlamaya bağlı olmayan yapısal alanlar
(`liquidation_preference_usd`, `par_value_usd`, adet) ön prospektüste de dolu olabilir.

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

`offered_unit` değerleri: `"share"` · `"depositary_share"` · `"note"`.
`"note"` gözlemlenen bir kenar durumdur, uydurma değil: Banco Santander AT1 ihraçları
imtiyazlı-benzeri (süresiz, birikimsiz, sermaye benzeri) ama yapısal olarak **tahvil** —
*"a liquidation preference of $200,000 per Note"*. Kapsam dışı sayılmadılar çünkü
etiketleri metinle doğrulanabiliyor; ama `shares_offered` bunlarda anlamsızdır → `null`.

**Kendi kendini kontrol et:** `shares_offered × liquidation_preference_usd` ihracın
toplam büyüklüğünü vermeli ve bu **10 milyon – 10 milyar dolar** aralığında olmalı.
Bu aralığın 100 katı çıkıyorsa birimleri karıştırmışsındır.

*(Tavan önce 5 milyardı; iki ajan bağımsız olarak Alphabet'i işaretledi:
`167.500.000 × $50 = 8,375 milyar` ve bu rakam ilanın kendi fiyatlama tablosundaki
`Total $8,375,000,000` ile birebir eşleşiyor. Yani etiket doğru, **tavan yanlıştı** —
mega-cap ihraçlarını hesaba katmıyordu. Aralığı zorlamak için etiketi bozma;
metin ve tablo doğruluyorsa metne uy.)*

📌 **Hatanın gerçek şekli:** ilk turda etiketçiler "ilk gördüğü sayıyı" almadı,
**sistematik olarak BÜYÜK dolar rakamına yöneldi** — metin `$25 per depositary share
(equivalent to $1,000 per share)` diye ters sırada yazsa bile 1.000'i seçti.
Büyük sayı daha "önemli" görünüyor; kural bunu bilerek karşılamalı.

### 🔴 G) BOOL ALANLAR — sessizlikten `false` ÇIKARMA

Ölçüldü: `cumulative` 43 kez `false` etiketlendi çünkü başlıkta açıkça **"Non-Cumulative"**
yazıyor. `convertible` ise 87 belgenin yalnız **1'inde** açıkça olumsuzlanıyor.

**Kural: bir bool yalnızca metin AÇIKÇA olumsuzluyorsa `false` olur. Sessizlik → `null`.**

- `Non-Cumulative` yazıyor → `cumulative: false` ✅
- `convertible` kelimesi hiç geçmiyor → `convertible: null` ✅ (`false` DEĞİL)

Sebep: etiket, modele verilen **metinde ne olduğunu** tanımlar, menkul kıymetin gerçeğini
değil. Sessizlikten `false` üretirsek modele "girdide olmayan şeyi tahmin et" öğretmiş
oluruz — tam da engellemeye çalıştığımız davranış.

### I) `series` TEK BAŞINA menkul kıymeti tanımlamaz

Ölçüldü (test kümesi): Strategy Inc'in **dört ayrı imtiyazlısı da "Series A"** adını taşıyor,
ayrım isimde:

| başlık | kısaltma | kümülatif |
|---|---|---|
| `10.00% Series A Perpetual **Strife**` | STRF | evet |
| `10.00% Series A Perpetual **Stride**` | STRD | **hayır** |
| `8.00% Series A Perpetual **Strike**` | STRK | · |

Yani aynı ihraççıda aynı seri harfi, farklı kupon ve farklı kümülatiflik. Etiketler doğruydu;
ilk bakışta "çelişki" sanılan şey gerçek bir ayrımdı.

📌 **Bilinen sınır:** ayırt edici ad (`Perpetual Strife`) şu an hiçbir alana yazılmıyor.
Veri setini menkul-kıymet düzeyinde eşleştirmek gerekirse `series` yetmez, başlık metni gerekir.

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
- Depositary share yapısı → **§F'ye bak.** `liquidation_preference_usd` her zaman
  **teklif edilen birim başına**dır ($25), alttaki imtiyazlı hissenin değeri ($25.000) değil.
  *(Bu madde önce tersini söylüyordu ve §F ile çelişiyordu; 2026-07-31'de düzeltildi.)*

## Kalite

Emin olamadığın alanı `null` bırak ve `evidence`'a not düşme. Bu veri seti bir
**ölçüm** için kuruluyor; uydurulmuş bir etiket, ölçümün tamamını geçersiz kılar.
