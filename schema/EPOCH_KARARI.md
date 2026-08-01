# `--epochs 5` denemesi — KARAR KURALI (koşudan ÖNCE yazıldı)

Bu belge 5 epoch koşusu **başlamadan önce** commit edilmiştir. Amacı tek: eşiği sonuca
bakarak belirleme imkânını ortadan kaldırmak. Sonucu görüp "aslında 1 kayıt da yeterli"
demek, ölçümü ölçüm olmaktan çıkarır.

## Neden bu deneme var

README ve Evidence notu şunu söylüyor: dev'de hem tam kayıt hem `eval_loss` **3. epoch'ta
hâlâ iyileşiyordu**. Yani 3 epoch'un en iyi olduğu gösterilmedi; yalnızca 1 ve 2'yi yendiği
gösterildi. Bu açık bir uç ve kapatılması gerekiyor — hangi yöne kapanırsa kapansın.

## Referans (mevcut yapılandırma)

3 epoch koşusu, `dev` (25 kayıt), checkpoint seçimi:

| checkpoint | dev tam kayıt | dev `eval_loss` |
|---|---|---|
| 13 (epoch 1) | %48,0 (12/25) | 0,01938 |
| 26 (epoch 2) | %60,0 (15/25) | 0,01551 |
| **39 (epoch 3)** | **%68,0 (17/25)** | **0,01169** |

**Aşılması gereken çubuk: 17/25.**

## ⚠️ Bu bir DEVAM değil, YENİ koşudur

`train_lora.py` öğrenme oranı zamanlayıcısını açıkça ayarlamıyor, yani transformers
varsayılanı olan **linear decay** geçerli ve zamanlayıcı **toplam adım sayısına** göre
kuruluyor. 3 epoch = 39 adım, 5 epoch = 65 adım. Dolayısıyla 5 epoch koşusundaki
`checkpoint-39`, 3 epoch koşusundaki `checkpoint-39` ile **aynı model değildir** — o noktada
öğrenme oranı farklıdır. Karşılaştırma "4. ve 5. epoch işe yaradı mı" değil, şudur:

> **5 epoch koşusunun dev'deki EN İYİ checkpoint'i, 17/25'i geçiyor mu?**

## Karar kuralı

**Birincil sinyal:** dev tam kayıt (13/13 alan). 25 kayıtta 1 kayıt = 4,0 puan.

**Eşik: ≥ 19/25 (%76,0).** Yani en az **2 kayıt** iyileşme.

- **18/25 (%72,0) YETMEZ.** 25 kayıtlık bir dilimde tek kayıtlık fark gürültü
  mertebesindedir; yapılandırma değiştirmek için delil sayılmaz.
- **İkincil sinyal:** seçilen checkpoint'in `eval_loss` değeri de 0,01169'un altında olmalı.
  **İki sinyal çelişirse 3 epoch kalır.** Beraberliği mevcut yapılandırma kazanır: değişiklik
  yapmak için delil gerekir, delilin yokluğu değişiklik gerekçesi değildir.

## Sonuca göre ne yapılır

**A) En iyi dev ≥ 19/25 VE `eval_loss` < 0,01169** → yapılandırma 5 epoch olur.
Test **bir kez** yeniden koşulur ve raporda açıkça **"test setinin İKİNCİ ölçümü"** diye
etiketlenir. Birinci ölçümün sayıları silinmez; ikisi yan yana durur ve ikinci bakışın
yapıldığı yazılır.

**B) Diğer her durum** → 3 epoch kalır, **test'e DOKUNULMAZ.**
Sonuç yine de yazılır: *"5 epoch dev'de denendi, çubuğu geçmedi."* Negatif sonuç da
sonuçtur; README'deki "3 epoch optimum değil, bu canlı bir uç" cümlesi bu durumda
"denendi, iyileştirmedi" olarak güncellenir.

## Koşu kısıtları

- **Adaptörün üzerine YAZILMAYACAK.** 3 epoch adaptörü yayınlanmış sayıların arkasındaki
  tek artifact. 5 epoch koşusu ayrı dizine yazar:
  `--out models/lora-qwen2.5-1.5b-e5`
- Diğer her hiperparametre **aynı** kalır (`--rank 16`, `--lr 1e-4`, `--batch 1`,
  `--grad-accum 8`, `--max-length 3072`, `seed=42`). Tek değişen epoch sayısıdır; iki şeyi
  aynı anda değiştirmek hangisinin etki ettiğini ölçülemez yapar.
- 🔴 **TEK GPU'ya sabitlenir: `CUDA_VISIBLE_DEVICES=0`.** Kaggle'ın ücretsiz seçeneği
  **T4 ×2**; iki kart görünürse `transformers` Trainer `n_gpu > 1` görüp modeli
  `nn.DataParallel`'e sarar. O zaman etkin yığın 8 değil **16** olur, epoch başına
  optimizer adımı 13'ten ~7'ye düşer ve karşılaştırma sessizce bozulur — epoch sayısının
  yanında yığın boyutu da değişmiş olur. Kartın kendisi baz koşuyla aynı kalsın diye
  P100 yerine T4 seçilir, ikinci kart ise gizlenir.
- Seçim `dev` üzerinde yapılır. Bu koşu sırasında `test` bölmesine **hiçbir tahmin
  üretilmez**.

## Kayıt

| alan | değer |
|---|---|
| kural yazıldı | 2026-08-02, koşudan önce |
| koşu tarihi | *(koşulunca doldurulacak)* |
| 5 epoch en iyi dev | *(doldurulacak)* |
| `eval_loss` | *(doldurulacak)* |
| karar | *(A veya B)* |
