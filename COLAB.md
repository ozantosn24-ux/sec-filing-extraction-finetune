# Colab runbook — ücretsiz T4'te fine-tune ve ölçüm

Bu dosya, **hiç para harcamadan** adım ②'yi bitirip adım ③'ün üç yarışmacısını da
ölçmek için hücre hücre ne yapılacağını yazar.

> ⛔ **Yerelde koşmayın.** Bu makinede `torch` CPU-only kurulu ve 16 GB RAM var;
> 1,5B model fp32'de tek başına ~6 GB ağırlık demek. Ölçüldü: 135M model bu CPU'da
> (i5-9400) **32 sn/adım** — 1,5B kabaca 11 kat büyük, yani gün mertebesi ve makine
> o süre boyunca takasa girip kullanılamaz hale gelir. `train_lora.py` bunu zaten
> **engelliyor** (`--force-cpu` demedikçe durur).

---

## 0. Önce yedek (Colab'den önce, 1 dakika)

`data/interim/` ve `data/processed/` git'te **değil** (bilinçli: depo veriyi değil
veriyi üreten kodu versiyonluyor) ve deponun uzağı yok. Yani 160 etiketin tek
kopyası bu diskte. Colab'e dosya yüklemeden önce bir zip alın.

## 1. Colab'i GPU'ya alın ve DOĞRULAYIN

`Runtime → Change runtime type → T4 GPU`. Sonra:

```python
!nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv
```

Beklenen: `Tesla T4, 15360 MiB, 7.5`.

🔴 **`7.5` Turing demek, yani bf16 YOK.** Bu bir sorun değil — `train_lora.py`
kartın compute capability'sine bakıp fp16'yı kendisi seçiyor, siz bir şey
yapmıyorsunuz. Ama rehberlerden kopyaladığınız başka bir script `bf16=True`
(TRL'in varsayılanı) ile patlarsa sebebi budur.

## 2. Kurulum — sürümler SABİT

```python
!pip install -q transformers==5.14.1 trl==1.9.2 peft==0.20.0 datasets==5.0.1 accelerate==1.14.0 bitsandbytes==0.50.0
!pip uninstall -y -q torchao        # <- ATLAMAYIN, aşağıya bakın
```

🔴 **`torchao`'yu kaldırın — kurmayı değil, KALDIRMAYI kastediyorum.** Colab imajında
`torchao 0.10.0` hazır geliyor ve `peft 0.20.0`'ın LoRA dispatcher'ı onu görünce koşuyu
öldürüyor:

```
peft/tuners/lora/model.py -> dispatch_torchao()
peft/import_utils.py      -> is_torchao_available()
ImportError: Found an incompatible version of torchao.
             Found version 0.10.0, but only versions above 0.16.0 are supported
```

Kritik ayrıntı: eski sürümde `is_torchao_available()` **`False` dönmüyor, `ImportError`
atıyor**. Yani "torchao kullanmıyoruz" sizi korumuyor — dispatcher her LoRA katmanı için
çağırıyor ve `SFTTrainer` kurulurken patlıyor. Hata *eğitimin içinde* değil, trainer
daha kurulurken çıkıyor.

**Bu, yerelde ASLA görünmeyen bir arıza.** Bu depoda torchao hiç kurulu değil, `find_spec`
`None` dönüyor, fonksiyon temizce `False` veriyor — CPU smoke testi bu yüzden geçiyordu.
Ölçüldü (2026-08-01, Colab T4): aynı script, aynı sürümler, aynı veri; fark yalnız ortam.
"Yerelde geçti" bu sınıf arızayı yakalamaz — smoke testini **koşacağınız makinede**
tekrar koşmanızın sebebi tam olarak budur.

Sürümler neden sabit: TRL'in SFT API'si bu proje yazılırken değişti
(`max_seq_length` → `max_length`, varsayılan 1024). Eski adı veren script **hata
vermez**, sessizce her örneği keser. Ayrıntı: `requirements-train.txt`.

`bitsandbytes` yalnız 4. adımdaki 7B yarışmacısı için gerekli.

## 3. Dosyaları yükleyin

Gereken **yedi** dosya — dördü veri, üçü kod:

```
data/processed/sft_train.jsonl      (~1,8 MB)
data/processed/sft_dev.jsonl        (~0,5 MB — SEÇİM seti, aşağıya bakın)
data/processed/sft_test.jsonl       (~0,6 MB)
data/processed/token_report.json    (küçük — ATLAMAYIN, aşağıya bakın)
src/prompt.py
src/train_lora.py
src/predict.py
```

🔴 **`sft_dev.jsonl`'i atlamayın.** Bu, train'den şirket bazında oyulmuş 25 kayıtlık
**seçim** setidir; `train_lora.py` her epoch sonunda üzerinde `eval_loss` ölçer.
Yoksa script çalışır ama açık bir uyarı basar ve "kaçıncı epoch daha iyi" sorusunu
cevaplayacak tek temiz sinyal kaybolur — geriye yalnız test'e bakmak kalır, o da
karşılaştırmayı kirletir.

🔴 **`token_report.json`'ı atlamayın.** `train_lora.py`'ın kesme koruması ölçülen tabanı
(2.626 token) bu dosyadan okuyor; dosya yoksa koruma **sessizce devre dışı kalır** ve
düşük bir `--max-length` verirseniz hiçbir şey sizi durdurmaz. Ölçüldü: izole bir
ortamda `--max-length 2048` engellenmedi. Dosya olmadan script çalışır ama açık bir
uyarı basar — o uyarıyı görürseniz eksik yüklemişsinizdir.

(Bu liste izole bir dizinde denendi: yalnızca bu altı dosyayla smoke test ve üretim
koşuyor, başka bir şey gerekmiyor.)

Colab'de aynı ağaç yapısını kurun (script'ler `ROOT/data/processed` bekliyor):

```python
import os
os.makedirs("edgar-extract/data/processed", exist_ok=True)
os.makedirs("edgar-extract/src", exist_ok=True)
# sol paneldeki dosya simgesinden yükleyin, sonra:
%cd edgar-extract
```

## 4. Önce SMOKE — gerçek modelle, 2 dakika

```python
!python src/train_lora.py --smoke
```

Bu hücre öğrenme için değil. Baktığınız tek satır:

```
kayip maskesi: 2294 token'in 108'sinde kayip hesaplaniyor (%4.7)
```

**%5 civarı olmalı.** Bu, kaybın yalnız JSON hedefinde hesaplandığı anlamına gelir —
700 token'lik talimat maskeleniyor. Oran yarıdan büyük çıkarsa `completion_only_loss`
çalışmıyordur ve model **talimatı üretmeyi** öğrenir; 3 saat sonra değil, şimdi durun.

Sonra gerçek modelle VRAM'i ölçün:

```python
!python src/train_lora.py --probe
```

`--probe`, veriyi **token uzunluğuna göre sıralayıp en uzun dizilerle** iki adım koşar
ve adaptörü kaydetmez. Sıralama şart: kayıtlar accession'a göre dizili, yani ilk
adımlar rastgele uzunlukta. Ölçüldü — dosya sırasındaki ilk üç kayıt en uzun üçü
**değil**; en uzun dizi 2.626 token ve listenin başında değil. Uzunluğa bakmayan bir
prob (eski hâli: `--epochs 0.05`) rahatlıkla geçer, asıl koşu ilerideki uzun örnekte
OOM verir — yani kiralık saatin ortasında.

Çıktının sonundaki `tepe VRAM: X.XX GB / 15.4 GB (%N)` bir **tavandır**. **%85'in
altındaysa** asıl koşu rahat sığar; üstündeyse sırayla: `--rank 8` → `--4bit`.
`--max-length 3072` sabit kalsın, **düşürmeyin** — kesme veriyi bozar ve metrikte
"model bulamadı" diye görünür.

Gradient checkpointing **açık** (varsayılan). Qwen2.5'in kelime dağarcığı 151.936;
3.072 uzunlukta logit tensörü tek başına fp16'da ~0,9 GB, kayıp için fp32'ye çıkınca
~1,9 GB, bir de gradyanı. Aktivasyonları yeniden hesaplamak ~%30 yavaşlatır — 37
adımlık bir koşuda bu dakikalar demek, OOM ise kiralık saatin tamamı demek.

## 5. Gerçek koşu

```python
!python src/train_lora.py
```

Varsayılanlar: Qwen2.5-1.5B-Instruct, LoRA r=16, 3 epoch, lr 1e-4, `max_length=3072`
(ölçülen taban 2.626; script bunun altına düşerseniz durur).

Koşu başında basılan iki satıra bakın:

```
dev ornegi   : 25  (SECIM seti — sonuc buradan raporlanmaz)
optimizer adimi: ~36  (99 ornek / etkin yigin 8 x 3 epoch)
```

🔴 **Optimizer adımı 36** — örnek sayısı değil, LoRA'nın gerçekten kaç kez
güncellendiği. Bu az. Epoch sonlarındaki `eval_loss` **düşmeye devam ediyorsa** koşu
erken bitmiş demektir; `--epochs 5` ya da `--grad-accum 4` (etkin yığın 4 → ~74 adım)
deneyin. Bu kararı **dev'e bakarak** verin, test'e değil.

🔴 **Drive'a yazın — bu isteğe bağlı DEĞİL.** `save_strategy="epoch"` adaptörü her
epoch sonunda kaydediyor, ama `/content` **oturumla birlikte silinir**. Ölçüldü
(2026-08-01): oturum koptu, 18 dakikalık eğitimin adaptörü ve tüm tahmin dosyaları
gitti — checkpoint'lerin varlığı işe yaramadı, çünkü hepsi `/content` altındaydı.
"Kopmada baştan başlamazsınız" yalnızca oturum **yaşarken** doğru.

```python
from google.colab import drive; drive.mount('/content/drive')
!python src/train_lora.py --out /content/drive/MyDrive/edgar-extract/lora-qwen2.5-1.5b
```

Tahminleri de aynı yere yazın (`-o /content/drive/MyDrive/edgar-extract/...`). Drive'a
yazmak epoch başına birkaç saniye ekliyor (ölçüldü: `train_runtime` 1083 sn → 1147 sn,
%6) — kaybedilen koşunun yanında hiçbir şey.

🔴 **fp16 uyarısı:** loss `nan` olursa **ilk şüpheli fp16'dır**, model ya da veri
değil. T4'te bf16 yok, o yüzden çare `--lr 5e-5` gibi daha düşük bir öğrenme oranı
ya da Ampere+ bir kart. Veriyi kurcalamadan önce bunu deneyin.

## 6a. Önce SEÇİM — hangi epoch? (dev üzerinde, test'e DOKUNMADAN)

`save_strategy="epoch"` her epoch'un adaptörünü `checkpoint-*/` altında bırakıyor.
Hangisinin alınacağı **dev'de** ölçülerek seçilir:

```python
import glob, subprocess
for ck in sorted(glob.glob("models/lora-qwen2.5-1.5b/checkpoint-*")):
    ad = ck.split("-")[-1]
    subprocess.run(["python","src/predict.py","--adapter",ck,"--split","dev",
                    "-o",f"data/processed/preds_ft_dev_{ad}.jsonl"], check=True)
```

Sonra yerelde (ya da burada) `python src/evaluate.py data/processed/preds_ft_dev_*.jsonl --split dev`
ve **tam kayıt** en yüksek olanı seçin. `eval_loss` düşük varyanslı ama vekil bir
sinyal; tam kayıt asıl önem verdiğimiz metrik, 25 kayıtta gürültülü (std hata ~%9).
İkisi çelişirse tam kaydı seçin ve farkı rapora yazın.

⛔ **Dev skorunu sonuç diye raporlamayın.** Regex bu 25 kaydı kendi geliştirme
verisinde gördü (ölçüldü: dev'de %68,0, test'te %27,8) — dev'de regex ile
fine-tuned modeli yan yana koymak yanlış karşılaştırmadır. Dev yalnızca
**fine-tuned checkpoint'leri birbiriyle** kıyaslamak içindir.

## 6b. Üç yarışmacının çıktısını üretin (SEÇİLEN checkpoint ile)

```python
# 1) fine-tuned küçük model — 6a'da secilen checkpoint
!python src/predict.py --adapter models/lora-qwen2.5-1.5b/checkpoint-SECILEN

# 2) prompted ORTA BOY model — aynı T4'te, 4-bit. 7B DEĞİL, aşağıya bakın.
!python src/predict.py --model Qwen/Qwen2.5-3B-Instruct --4bit -o data/processed/preds_prompted3b_test.jsonl

# 3) AYNI küçük modelin ADAPTÖRSÜZ hali — LoRA'nin gercekten fark yaratip
#    yaratmadigi ancak bu olcumle bilinir. Adaptorlu skor tek basina, modelin
#    zaten bilip bilmedigini AYIRT ETMEZ.
!python src/predict.py -o data/processed/preds_base1.5b_test.jsonl
```

Dördüncüsü (kural-tabanlı regex) **yerelde zaten ölçüldü**, GPU istemiyor.

🔴 **7B, ücretsiz Colab'de OTURUMU ÖLDÜRÜYOR — ölçüldü (2026-08-01).** Önceki tahmin
şuydu: "NF4'te ~4 GB ağırlığı var, 16 GB'a sığmalı." VRAM tarafı doğru ama **darboğaz
VRAM değil**: `--4bit` taban modeli 4-bit *yükler*, ama önce fp16 ağırlıkları
**indirmek** zorunda — Qwen2.5-7B için **15,2 GB**. İndirme %32'deyken oturum
kaynaklarını tüketti ve runtime düştü; `/content` ile birlikte adaptör ve o ana kadarki
tüm tahminler gitti.

Bu yüzden varsayılan `Qwen2.5-3B-Instruct` (~6 GB indirme). Raporda dürüst karşılık:
yarışmacı "prompted **orta boy** açık model", "büyük model" değil.

⚠️ Sonuç olarak bu kurulumun dürüst sınırı daha da dar: **"küçük fine-tuned model,
orta boy prompted açık modeli yener"**. Claude/GPT sınıfı bir modelle karşılaştırma
bu runbook'ta YOK ve öyle sunulmamalı.

## 7. Sonuçları indirin ve YERELDE ölçün

```python
from google.colab import files
files.download('data/processed/preds_ft_test.jsonl')
files.download('data/processed/preds_prompted7b_test.jsonl')
```

Ölçüm yerelde koşar (GPU istemez) ve üçünü yan yana basar:

```bash
python src/evaluate.py \
  data/processed/preds_regex_test.jsonl \
  data/processed/preds_ft_test.jsonl \
  data/processed/preds_prompted7b_test.jsonl \
  --json-out data/processed/eval_all.json
```

Adaptörü de indirin (`models/lora-.../` klasörü) — birkaç MB, artifact'ın kendisi.

---

## Aşılması gereken çubuk

Kural-tabanlı baseline test kümesinde (36 kayıt) şunu yapıyor:

| metrik | regex |
|---|---|
| şema geçerliliği | %100 (yapısı gereği) |
| tam kayıt (13/13) | **%27,8** |
| doğru abstention | %90,2 |
| uydurma | %9,8 |
| zor vaka (par↔liq) | **%81,6** |
| tek-örnek `unit` | isabet |

Fine-tuned model **tam kayıt** ve **zor vaka**'da bunu geçmezse, sonuç "fine-tune
bu görevde kural-tabanlıyı yenmedi" olur ve **öyle raporlanır**. Ölçümün amacı
kazanmak değil, öğrenmek.

## Bu yolun dürüst sınırı

"Prompted büyük model" burada 7B açık bir model, Claude/GPT sınıfı değil. Yani
sonuç **"küçük fine-tuned model, orta boy prompted açık modeli yener"** olur —
daha fazlası değil. Raporda böyle yazılmalı.

Buna karşılık bir avantajı var ve gerçek: üç yarışmacı da **aynı donanımda, aynı
talimatla** koşuyor (`src/prompt.py` tek kaynak), dolayısıyla gecikme ve maliyet
karşılaştırması anlamlı. API'li bir baseline'da "küçük model mi iyiydi, ucuz
donanım mı" ayrışmazdı.

## Koşu bittiğinde

Adım ③'ün sayıları çıkar çıkmaz **Evidence notu** yazılmalı. G13 ve G08'in
`claim_ceiling`'i HAYIR'dan EVET'e ancak böyle döner — modülü okumak değil,
çalışan bir fine-tune + ölçüm bunu yapar. Kilidi açan şey script değil, sonuç.
