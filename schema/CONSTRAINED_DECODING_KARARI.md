# Constrained decoding — KARAR KURALI (koşudan ÖNCE yazıldı)

**Tarih:** 2026-08-19. Bu dosya, koşu yapılmadan ve test'e bakılmadan önce commit'lendi.
`schema/EPOCH_KARARI.md` ile aynı usul: eşiği sonradan gevşetmek geçmişte görünür.

## Soru

Prompted iki kol test'te **tam kayıtta 0/36** aldı. README'nin kabul ettiği sınır şu:
bu kollara *scaffolding verilmedi* — tek prompt, greedy, retry yok, repair yok.
En güçlü itiraz da bu: **"kazanç sadece JSON formatındandır."**

Bu koşu o itirazı test eder. Ölçülen şey şu tek soru:

> Çıktı şeması **zorla** dayatıldığında, prompted modeller fine-tuned modelin
> tam-kayıt skoruna yaklaşır mı?

## Neden bu, önceki post-hoc analizden farklı

README'deki "ham vs biçim-hariç" bölümü kaydedilmiş çıktılar üzerinde bir **muhasebe**ydi
ve tam kaydı oynatamıyordu. Bu koşu **üretimi** değiştiriyor: kısıtlı decoding sonraki
token'ları, dolayısıyla modelin okuduğu değerleri de değiştirir. Bu yüzden çıktı-tarafı
onarımının veremediği cevabı verebilir — ve tam da bu sebeple **yeni bir ölçümdür**,
yeniden skorlama değil.

## Koşulacak kollar (test, BİR KEZ)

| kol | model | not |
|---|---|---|
| base 1.5B + constrained | `Qwen/Qwen2.5-1.5B-Instruct` (pinli) | adaptörsüz |
| prompted 3B + constrained | `Qwen/Qwen2.5-3B-Instruct` (pinli), `--4bit` | yayınlanmış kolun aynısı |
| **fine-tuned + constrained** | 1.5B + `lora-qwen2.5-1.5b` | **kontrol kolu**, aşağıda |

Fine-tuned kol bir kontroldür, yeni bir iddia değil: zaten %100 şema-geçerli olduğu için
kısıt ona bir şey **kazandırmamalı**. Kaybettiriyorsa, kısıt ücretsiz değildir ve bu,
prompted kolların sonucunu okumayı da değiştirir. Yalnız rakibe scaffolding verip
şampiyona vermemek asimetrik olurdu.

## Sabit tutulanlar (kısıt DIŞINDA hiçbir değişken oynamıyor)

- aynı talimat (`src/prompt.py`), aynı test bölmesi (36 kayıt), aynı `max_new_tokens=160`
- **greedy** (`do_sample=False`) — kısıt biçimi zorlamak için var, ölçümü rastgeleleştirmek için değil
- aynı model pin'leri (`src/pins.py`), aynı 4-bit yapılandırması
- şema **elle yazılmadı**: `src/schema_json.py` onu `evaluate.py`'nin sabitlerinden türetiyor,
  böylece kısıtlama sözleşmesi ile skorlama sözleşmesi ayrışamaz (testlerle bağlandı)

## KARAR KURALI

Çubuk, fine-tuned kolun test'teki tam-kayıt skoru: **22/36 (%61,1)**.

1. **Constrained 3B tam kayıtta ≥ 22/36 alırsa:** manşet iddia bu hâliyle savunulamaz.
   README'nin başlığı, "prompted açık modeli yener" yerine **"scaffolding'siz koşulda yener"**
   diye daraltılır ve bu koşunun sayısı manşetin hemen yanına yazılır.
2. **Constrained 3B 22/36'nın altında kalırsa:** iddia, en güçlü scaffolding itirazına karşı
   ayakta demektir. Yeni bir üstünlük iddiası **kurulmaz**; yalnızca "bu itiraz denendi ve
   farkı kapatmadı" yazılır.
3. **Fine-tuned + constrained, 22/36'nın altına düşerse:** kısıt ücretsiz değildir. Bu durumda
   prompted kolların constrained skorları **tek başına** alıntılanmaz; her üçü birlikte verilir.

⛔ **Şema geçerliliğindeki artış BULGU DEĞİLDİR.** Kısıt 13 anahtarı zaten *inşa gereği*
zorluyor; şema geçerliliğinin ~%100'e çıkması mekanizmanın kendisidir, keşif değil. Bu satır
tabloda görünür ama "constrained decoding şema geçerliliğini düzeltti" diye **sunulmaz**.

## Yapılmayacaklar

- Koşu **bir kez**. Skor beğenilmediği için prompt, şema, `max_new_tokens` ya da kısıt
  ayarlanıp yeniden koşulmaz.
- Birden çok varyant koşulup **en iyisi seçilmez**. Bu dosyada yazan yapılandırma neyse o.
- Retry, repair, few-shot, sampling **eklenmez** — hepsi ayrı değişkenlerdir.
- `n=36` ve 22 şirket. İkinci ondalık, p-değeri ve genellenebilir üstünlük iddiası
  kullanılmaz.

## Raporlama

Sonuç ne çıkarsa çıksın README'ye yazılır ve **test'e üçüncü bakış** olduğu etiketlenir
(birincisi 08-01 dört yarışmacı, ikincisi 08-19 biçim muhasebesi). Yüzdelerin yanında
`n/36` verilir. Koşu başarısız olursa (kota, oturum, kütüphane) **"denendi, koşturulamadı"**
yazılır; kısmi sonuç manşete alınmaz.

## Koşudan önce ölçülenler (yığın gerçekten çalışıyor mu)

CPU smoke, `outlines` + `transformers==5.14.1`, pinli `SmolLM2-135M-Instruct`, **train**
bölmesinden 2 kayıt (test'e dokunulmadı):

- kısıtsız hâlde düz nesir üreten 135M model, kısıtla **13 anahtarlı** JSON üretti
- `evaluate.parse_prediction` her iki kayıtta da **sıfır ihlal** raporladı
- yani kısıtlama şeması ile skorlama şeması aynı şeyi söylüyor

⚠️ `outlines` **python < 3.14** istiyor. Deponun yerel ve CI ortamı 3.14, dolayısıyla
`--constrained` bu ortamlarda **kurulamaz**; Colab/Kaggle içindir. `bitsandbytes` ile aynı
sınıf bir bağımlılık ve aynı şekilde belgelenmiştir.

## Kayıt (koşu bitince doldurulacak)

| kol | şema geçerliliği | tam kayıt | abstention | uydurma | zor vaka |
|---|---|---|---|---|---|
| base 1.5B + constrained | | | | | |
| prompted 3B + constrained | | | | | |
| fine-tuned + constrained (kontrol) | | | | | |

**Sonuç:** _(kural 1 mi 2 mi 3 mü uygulandı — koşudan sonra yazılacak)_
