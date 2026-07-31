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
!pip install -q transformers==5.14.1 trl==1.9.2 peft==0.20.0 datasets==5.0.1 accelerate==1.14.0 bitsandbytes
```

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

Sonra gerçek modelle VRAM'i ölçün (bir epoch'un ilk adımları yeter, sonra durdurun):

```python
!python src/train_lora.py --epochs 0.05
```

Çıktının sonundaki `tepe VRAM: X.XX GB` sayısı, asıl koşunun sığıp sığmayacağını
söyler. **OOM'u 3 saatin 10. dakikasında değil burada görün.** Sığmazsa sırayla:
`--batch 1` (zaten öyle) → `--max-length 3072` sabit kalsın, **düşürmeyin** (kesme
veriyi bozar) → `--rank 8` → `--4bit`.

## 5. Gerçek koşu

```python
!python src/train_lora.py
```

Varsayılanlar: Qwen2.5-1.5B-Instruct, LoRA r=16, 3 epoch, lr 1e-4, `max_length=3072`
(ölçülen taban 2.626; script bunun altına düşerseniz durur).

**Oturum kopması:** adaptör her epoch sonunda kaydediliyor (`save_strategy="epoch"`),
yani kopmada baştan başlamazsınız. Kaydı **Drive'a** almak isterseniz:

```python
from google.colab import drive; drive.mount('/content/drive')
!python src/train_lora.py --out /content/drive/MyDrive/lora-qwen2.5-1.5b
```

🔴 **fp16 uyarısı:** loss `nan` olursa **ilk şüpheli fp16'dır**, model ya da veri
değil. T4'te bf16 yok, o yüzden çare `--lr 5e-5` gibi daha düşük bir öğrenme oranı
ya da Ampere+ bir kart. Veriyi kurcalamadan önce bunu deneyin.

## 6. Üç yarışmacının çıktısını üretin

```python
# 1) fine-tuned küçük model
!python src/predict.py --adapter models/lora-qwen2.5-1.5b

# 2) prompted BÜYÜK model — aynı T4'te, 4-bit
!python src/predict.py --model Qwen/Qwen2.5-7B-Instruct --4bit -o data/processed/preds_prompted7b_test.jsonl
```

Üçüncüsü (kural-tabanlı regex) **yerelde zaten ölçüldü**, GPU istemiyor.

7B'nin NF4'te ~4 GB ağırlığı var, 16 GB'a sığmalı — **ölçülmedi**, ilk koşuda
görülecek. Sığmazsa `Qwen2.5-3B-Instruct`'a düşün ve raporda öyle yazın.

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
