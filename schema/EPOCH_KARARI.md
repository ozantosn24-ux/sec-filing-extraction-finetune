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

---

# SONUÇ — 2026-08-02, koşuldu

**Koşu:** Kaggle, Tesla T4 (CC 7.5, tek karta sabitlendi), 5 epoch, 65 optimizer adımı,
`--out lora-qwen2.5-1.5b-e5`. 3 epoch adaptörüne dokunulmadı. **Test'e hiçbir tahmin
üretilmedi.**

| checkpoint | dev tam kayıt | `eval_loss` |
|---|---|---|
| 13 (epoch 1) | %52,0 (13/25) | 0,01934 |
| 26 (epoch 2) | %56,0 (14/25) | 0,01656 |
| **39 (epoch 3)** | **%76,0 (19/25)** | **0,01151** |
| 52 (epoch 4) | %68,0 (17/25) | 0,01072 |
| 65 (epoch 5) | %68,0 (17/25) | 0,01117 |

Çubuk (3 epoch koşusu): **17/25**, `eval_loss` **0,01169**.

## Karar: **B — 3 epoch KALIYOR, test'e DOKUNULMADI**

Kural **lafzen geçti** (19/25 ≥ 19/25 ve 0,01151 < 0,01169), ama B seçildi. Gerekçe üç
ölçülmüş maddeye dayanıyor, "sonuç hoşuma gitmedi"ye değil:

**1. Kazanan checkpoint 3. epoch'un checkpoint'i.** 4. ve 5. epoch dev'i **düşürdü**
(%76,0 → %68,0 → %68,0). Deney "daha fazla epoch iyidir" hipotezini desteklemiyor,
**çürütüyor**. Geçen şey "5 epoch", 5 epoch'a yayılmış LR zamanlayıcısının 3. epoch'ta
durdurulmuş hâli. Ön-kayıtta alternatif olarak tarif edilen yapılandırma bu değildi.

**2. `eval_loss` farkı ölçüm gürültüsünün ALTINDA.** Kazanç 0,01169 − 0,01151 =
**0,00018**. Aynı yapılandırmayla koşulan iki özdeş 3-epoch koşusu arasındaki fark ise
**0,00022** (0,01147 ↔ 0,01169, README "Training run, measured"). İkincil sinyal, aletin
çözebildiği eşiğin altında — sinyal değil, fp16 belirsizliği.

**3. Benimsemek dev'e aşırı uydurmak olurdu.** 25 kayıtlık bir dilimde 2 kayıtlık farkla
yapılandırma seçmek, bu deponun karşı savunma kurduğu şeyin ta kendisi. Buna karşılık
test'e ikinci bakışın bedeli **kalıcı** ve geri alınamaz.

## ⚠️ Kuralın kendi kusuru — kayda geçsin

Bu kuralı yazarken `eval_loss` için **yön** belirledim ("daha düşük olmalı") ama **asgari
fark** belirlemedim. Koşular-arası gürültünün ~0,0002 olduğu zaten Evidence notunda
yazılıydı; dolayısıyla kural, **gürültüyle geçilebilecek** şekilde kurulmuştu. Bir dahaki
ön-kayıtta eşik şöyle yazılmalı: *"`eval_loss` en az 0,0005 düşmeli"* — yönle değil,
ölçüm çözünürlüğünün üstünde bir farkla.

## Ne öğrenildi

**Epoch sayısını artırmak bu görevde yardımcı olmuyor.** README'nin "3 epoch'un optimum
olduğu gösterilmedi — bu canlı bir uç" cümlesi kapandı: denendi, iyileştirmedi, geriletti.
Hiperparametre araması hâlâ yapılmadı (lr, rank aranmadı) — o ayrı ve açık kalıyor.
