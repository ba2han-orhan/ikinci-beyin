---
name: beyin-doktor
description: Beynin sağlık kontrolü. Hook'lar, script'ler, hafıza dosyaları, günlük loglar, derleme durumu ve vault hijyeni tek tabloda raporlanır. "beyin doktor", "doktor", "sağlık kontrolü", "beyin çalışıyor mu", "hafıza bozuk mu" dendiğinde veya bir hafıza mekanizmasının sessizce çalışmadığından şüphelenildiğinde kullan.
---

# Beyin Doktoru

Bu skill beynin mekanik katmanını denetler: hook'lar tetikleniyor mu, script'ler çalışmış mı,
loglar tazeliğini koruyor mu, vault kirlenmiş mi. Amaç sessiz arızayı görünür yapmak.

## Nasıl çalışırsın

1. Vault kökünde (CLAUDE.md/AGENTS.md'nin bulunduğu klasör) çalış. Tüm yollar göreceli, mutlak yol yazma.
2. Aşağıdaki kontrolleri **Bash ile sırayla çalıştır**. Komutları olduğu gibi kullan, tahmin etme.
3. Her kontrolün çıktısını 🟢 / 🟡 / 🔴 olarak sınıfla.
4. Sonucu tek bir tabloda ver, her 🔴 için bir düzeltme satırı yaz.
5. En sonda tek cümlelik hüküm ver.

Kontroller salt okunurdur. Hiçbir şeyi kendiliğinden düzeltme, önce raporla, sonra kullanıcı
isterse düzelt.

## Kontroller

### 1. Hook dosyaları var mı ve çalıştırılabilir mi

```bash
for h in session-start prompt-counter session-end pre-compact; do f=".beyin/hooks/$h.sh"; if [ ! -f "$f" ]; then echo "$h: DOSYA YOK"; elif [ ! -x "$f" ]; then echo "$h: calistirilabilir degil"; else echo "$h: ok"; fi; done
```

🟢 dördü de `ok`. 🔴 eksik veya çalıştırılabilir değil.
Düzeltme: `chmod +x .beyin/hooks/*.sh`, dosya yoksa depodan kopyala.

### 2. Hook'lar settings.json içinde bağlı mı

```bash
for h in session-start prompt-counter session-end pre-compact; do if grep -q "$h.sh" .claude/settings.json 2>/dev/null; then echo "$h: bagli"; else echo "$h: SETTINGS ICINDE YOK"; fi; done
```

🟢 dördü de bağlı. 🔴 biri bile eksikse o hook hiç çalışmıyor demektir.
Düzeltme: `.claude/settings.json` içindeki `hooks` bloğuna eksik olayı ekle (SessionStart,
UserPromptSubmit, SessionEnd, PreCompact), sonra Claude Code'u yeniden başlat.

### 3. Özyineleme koruması her hook'ta var mı

```bash
for f in .beyin/hooks/*.sh; do if grep -q 'BEYIN_INVOKED_BY' "$f"; then echo "$(basename "$f"): guard var"; else echo "$(basename "$f"): GUARD YOK"; fi; done
```

🟢 hepsinde var. 🔴 eksik. Guard'ı olmayan hook, arka plan model CLI çağrısında tekrar
tetiklenir ve sonsuz döngü riski doğar.
Düzeltme: dosyanın shebang'inden hemen sonraki satıra `[ -n "${BEYIN_INVOKED_BY:-}" ] && exit 0` ekle.

### 4. python3 ve model CLI yolda mı

```bash
if command -v python3 >/dev/null 2>&1; then echo "python3: $(python3 -V 2>&1)"; else echo "python3: YOK"; fi; command -v claude >/dev/null 2>&1 \&\& echo "model: claude var" || echo "model: claude YOK"
```

🟢 python3 ve `claude` var. 🔴 biri yoksa arka plan özetleyici ve derleyici durur.
Düzeltme: python3'ü ve Claude Code CLI'yi PATH'e ekle.

### 5. python3-missing işareti

```bash
if [ -f .beyin/scripts/.state/python3-missing ]; then echo "isaret VAR, tarih: $(head -1 .beyin/scripts/.state/python3-missing 2>/dev/null)"; else echo "isaret yok"; fi
```

🟢 işaret yok. 🔴 işaret var: hook'lar python3 bulamadığı için JSON kaçışını yapamamış.
Düzeltme: python3'ü kur, sonra dosyayı sil: `rm .beyin/scripts/.state/python3-missing`.

### 6. Günlük log tazeliği

```bash
# 'ls' bazi makinelerde eza/exa/lsd'ye alias'lidir ve -t farkli sozdizimi bekleyebilir;
# 'command ls' gercek binary'yi cagirir, alias'i bypass eder.
f=$(command ls -t 800-gunluk-oturum-kayitlari/*.md 2>/dev/null | head -1)
if [ -z "$f" ]; then
  echo "daily: hic log yok"
else
  # GNU stat'ta -f BSD'dekinden farkli anlama gelir (dosya degil dosya sistemi bilgisi)
  # ve hata vermeden yanlis/coklu satir dondurebilir; rakam olup olmadigini dogrula.
  m=$(stat -f %m "$f" 2>/dev/null || :)
  case "$m" in ''|*[!0-9]*) m=$(stat -c %Y "$f" 2>/dev/null || :) ;; esac
  n=$(date +%s)
  echo "daily: $f, $(( (n - m) / 3600 )) saat once yazildi"
fi
```

🟢 48 saatten yeni. 🟡 48 ile 96 saat arası. 🔴 96 saatten eski veya hiç log yok.
Düzeltme: oturum bitir ve yeniden başlat, sonra bu kontrolü tekrarla. Hâlâ boşsa 1, 2 ve 4
numaralı kontrollere dön, arıza flush zincirinde.

### 7. Derleme durumu

```bash
f=".beyin/scripts/.state/compile-state.json"
if [ -f "$f" ]; then
  # ayni GNU/BSD stat -f sorunu (bkz. check 6); rakam olup olmadigini dogrula
  m=$(stat -f %m "$f" 2>/dev/null || :)
  case "$m" in ''|*[!0-9]*) m=$(stat -c %Y "$f" 2>/dev/null || :) ;; esac
  n=$(date +%s)
  echo "state: $(( (n - m) / 3600 )) saat once guncellendi"
  python3 -c "import json;d=json.load(open('.beyin/scripts/.state/compile-state.json'));print('last_run:',d.get('last_run','yok'));print('last_status:',d.get('last_status','yok'));print('ingested:',len(d.get('ingested',{})),'log')" 2>/dev/null || echo "state dosyasi bozuk, JSON okunamadi"
else
  echo "compile: state dosyasi yok, henuz hic derleme calismadi"
fi
```

🟢 `last_run` 48 saatten yeni ve `last_status` `ok`. 🟡 state yok ama vault yeni kurulmuş veya
henüz akşam 18:00 olmamış. 🔴 `last_status` `fail:` ile başlıyor veya 48 saatten eski.
Düzeltme: elle bir tur çalıştır ve hatayı gör: `python3 .beyin/scripts/compile.py --dry-run`,
sonra `python3 .beyin/scripts/compile.py`.

### 8. Sağlık kayıtlarındaki son hatalar

```bash
if [ -f .beyin/scripts/.state/health.json ]; then tail -c 2000 .beyin/scripts/.state/health.json; else echo "health: kayit yok"; fi
```

🟢 kayıt yok veya son kayıt 7 günden eski. 🔴 son 48 saatte hata kaydı var.
Düzeltme: `component` alanına bak. `flush` ise transkript veya model CLI, `compile` ise model
çağrısı sorunlu. Hatayı okuduktan sonra dosyayı silebilirsin, script yeniden yazar.

### 9. Bilgi indeksi büyüklüğü

```bash
python3 .beyin/scripts/context_health.py --check index
```

🟢 indeks var ve makale sayısı okunuyor. 🟡 makale sayısı sıfırsa vault'un yeni olup
olmadığını kontrol et. 🔴 dosya yok/okunamıyor. Kanca yalnız sayı ve kaynak işaretçisi
verir; satır sayısı enjeksiyon taşması değildir. İndeks makine üretimidir; düzeltme
üretici/derleyici üzerinden yapılır.

### 10. Git deposu ve kaydedilmemiş değişiklik

```bash
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then echo "git: var, kaydedilmemis: $(git status --porcelain | wc -l | tr -d ' ') dosya"; else echo "git: REPO YOK"; fi
```

🟢 repo var ve kaydedilmemiş dosya 50'nin altında. 🟡 50 üstü birikmiş. 🔴 repo yok, yani
hafızanın geri alınabilir bir geçmişi yok.
Düzeltme: repo yoksa `git init` ve ilk commit. Birikme varsa commit at.

### 11. Sürüm dosyası

```bash
if [ -f .beyin-version ]; then echo "surum: $(head -1 .beyin-version)"; else echo "surum: DOSYA YOK, v1 vault"; fi
```

🟢 `2.3.0`. 🟡 `2.2.0`, `2.1.0`, `2.0.0` veya dosya yok: yükseltme yapılabilir.
Düzeltme: SETUP.md içindeki yükseltme yolunu (B modu) uygula. Yükseltme mevcut hafıza
dosyalarına dokunmaz, sadece eksik parçaları ekler.

### 12. Kurallar dosyası

```bash
if [ -f "850-hafiza/davranis-kurallari.md" ]; then echo "kurallar: var, $(wc -l < "850-hafiza/davranis-kurallari.md" | tr -d ' ') satir"; else echo "kurallar: YOK"; fi
```

🟢 var. 🟡 yok: Kullanıcının düzeltmeleri kalıcı hale gelmiyor.
Düzeltme: depodaki tohum `davranis-kurallari.md` dosyasını `850-hafiza/` altına kopyala.

### 13. Çift etkin kanca (settings.json + settings.local.json)

```bash
python3 .beyin/scripts/context_health.py --check hooks
```

🟢 her olay `ok`. SessionStart için tek `hepsi` veya birer `kurallar` ve `hafiza`
geçerlidir; iki farklı parça Claude'un kasıtlı limit ayrımıdır. Diğer üç olay birer
`hepsi` gerektirir. 🔴 `BOZUK`: aynı parça tekrar edilmiş, tam ve bölünmüş çağrı
karışmış, argüman tanınmıyor veya kayıt yok. Komutlar çalıştırılmaz; yalnız parça ve
sayıları gösterilir, ayarların diğer alanları çıktıya taşınmaz.
Düzeltme: iki Claude ayar dosyasındaki ilgili kayıtları karşılaştır; kasıtlı farklı
parçaları koru, aynı parçanın fazladan kaydını kaldır. İlgisiz kanca ve ayarlara dokunma.

### 14. Vault içinde sır taşıyabilecek yedek artığı

```bash
find . -path ./.git -prune -o -type f \( -name "*.yedek" -o -name "*.yedek-*" -o -name "settings.local.json.*" -o -name "*.bak" -o -name "*.orig" \) -print 2>/dev/null | head -10; echo "---"; git ls-files 2>/dev/null | grep -E 'settings\.local\.json|\.yedek|\.env$' || echo "izlenen sirli dosya yok"
```

🟢 iki bölüm de boş. 🔴 bir yedek dosyası çıkarsa: bu dosyalar `settings.local.json`
kopyası olabilir ve API anahtarı taşır; ikinci bölümde bir şey çıkarsa sır zaten git
tarafından izleniyor demektir.
Düzeltme: yedeği vault dışına taşı ve `chmod 600` ver; git izliyorsa
`git rm --cached <dosya>` ile izlemeden çıkar, `.gitignore` kuralını doğrula, ve
sızmış anahtarı sağlayıcıdan **iptal edip yenile**.

### 15. Seçilen kural kaynağı, bölüm limitleri ve teslim ölçümü

```bash
python3 .beyin/scripts/context_health.py --check rules
python3 .beyin/scripts/context_health.py --check metrics
python3 .beyin/scripts/context_health.py --check topics
```

Kaynak seçimi kancayla aynıdır: `calisma-cekirdegi.md` varsa o, yoksa
`davranis-kurallari.md`; `## Kurallar` ile `## Nasıl büyür` arası ölçülür.
`rules_part` Claude'un ayrı kurallar teslimi, `rules` birleşik teslim limitidir.
Tüm bölüm limitleri `session-start.sh` kodundan okunur.

🟢 seçilen kaynak sınırın %85'inden küçük ve limit okunabilir. 🟡 %85 veya
üstü. 🔴 limitten büyük ya da `OKUNAMADI`; eşitlik tek başına kırpılma değildir.
Düzeltme: gerçekten seçilen çekirdeği sadeleştir veya gerekçeli limit değişikliğini
bütçeyle birlikte yap; 23.000 birleşik / 9.900 hafıza bütçesini kontrol et.

Teslim raporunda `section_trimmed` bölüm sınırı aşımını, `budget_trimmed` toplam
bütçe kesilmesini, `omitted_topics` konu seçimi veya kesilmesiyle atlanan kayıtları
ayrı gösterir. `trimmed` ikisinden biri olduğunda artar. Son teslimler parça bazlı
`input_chars`, `capped_chars`, `emitted_chars`, `limit`, `omitted_topics` taşır;
metin saklanmaz. Atlanan konu sayısı tek başına arıza değildir, ayrıntıya erişim
ve seçim önceliğini inceleme sinyalidir. `legacy_delivered` eski şemasız kayıtlardır;
onlarda bölüm kırpılması bilinmiyor, sıfır ölçümü başarı kanıtı sayılmaz.
Ölçümde `char_unit` Bash için `unicode`, PowerShell için `utf16` olur; sınırdaki emoji
kesimleri iki platformda farklı olabilir. Windows çalıştırma testi olmadan çıktı paritesi
doğrulandı denmez. Son 200 denemede iki Claude parçası iki teslimdir; toplamı oturum sayısı değildir.
`unfinished_over_30s` kesinti belirtisidir, kesin timeout kanıtı değildir.

Konu modelinde `Status`, `Karar`, `Sonraki adım`, `Kaynak` alanlarının her biri bir kez
bulunmalı. 🟢 `konu modeli: ok`; 🔴 eksik/yinelenmiş alan veya boş liste. Kaynağı
kısaltırken [[aktif-konu-gecmisi]] içindeki tarihsel ayrıntıları koru.
`thread_selection` öncelik/proje/sorgu kipini gösterir; `unavailable` ise seçici
çalışmamıştır, kanca yalnız kaynak işaretçisi verir. Seçici tam özet ve kaynak
bağlantısını bütçeye sığdırır; atlananlar kaynak listede kalır. Native SessionStart
Kullanıcı sorgusunu varsaymaz, yalnız varsa `cwd` ile proje eşleştirir. Sorgu seçimi
`select_threads.py --query` ile ayrıca sınanır.

### 16. Sessiz hata sayaçları

```bash
python3 .beyin/scripts/hata_sayaci.py
```

`flush.py` ve `compile.py` içindeki hook-sınırı `except Exception` blokları
kasıtlı olarak hatayı yutar (çağıranı asla düşürmemek için); bu, hatanın hiç görünmemesi
anlamına gelmez. Her yutma noktası artık `.beyin/scripts/hata_sayaci.py` üzerinden
`.beyin/scripts/.state/hata-sayaclari.json` içine kaynak başına sayaç, son görülme zamanı ve
istisna sınıfı adı yazıyor (mesaj metni asla tutulmaz, sır taşıyabilir).

🟢 kayıt yok, ya da tüm kaynaklarda son görülme 7 günden eski. 🟡 bir kaynakta son 48 saat
içinde 1-2 kayıt var. 🔴 bir kaynakta son 48 saatte 3+ kayıt var ya da sayı hızla büyüyor —
bir hook sessizce düzenli olarak patlıyor demektir, `component` alanına bakan check 8 bunu
her zaman yakalamaz çünkü `health.json` sadece son hatayı tutar, bu sayaç birikimi gösterir.
Düzeltme: `kaynak` alanına bak (`compile.run_locked` gibi), ilgili dosyadaki `except Exception as exc:` bloğunun hemen
öncesini oku, kök nedeni düzelt. Sayaç kendiliğinden sıfırlanmaz:
`python3 .beyin/scripts/hata_sayaci.py --sifirla` ile temizle, sonra check'i tekrar çalıştır.

### 17. Hata defteri

```bash
python3 .beyin/scripts/hata_defteri.py rapor; grep -c hata-yakalayici .claude/settings.json; find .beyin/scripts/.state -name hata-olaylari.jsonl -mtime -7
```

Hata yakalayıcı `UserPromptSubmit` + `PostToolUseFailure` olarak kayıtlı olmalı; analiz oturum
sonunda flush'tan koşar. 🟢 sayaç `2`, rapor çalışıyor, `TEKRARLADI` satırı yok. 🟡 son 7 günde kayıt
dosyası yazılmamış (hiç hata olmadıysa normal; bir başarısız komutla dene) ya da `BEKLEYEN`
satırları var (Kullanıcıya hata-defteri skill'ini öner). 🔴 hook kaydı eksik ya da `TEKRARLADI`
var: uygulanan bir çözüm tutmamış.

### 18. Aktarım borcu ve kesilmiş işler

```bash
python3 .beyin/scripts/flush_recovery.py
```

Varsayılan denetim salt-okunurdur; çıktıda yalnız oturum hash kısaltması, durum/kilit,
sahip sınıfı ve kaynak türü bulunur. Transkript, model çıktısı ve ayar hata değeri basılmaz.
`unavailable` yapılandırılmış kaynakta erişim yok demektir, kalıcı kayıp kanıtı değil.
`owner=unknown` eski/Windows kaydında süreç doğum kimliği yok demektir; süreç öldü denmez.
🟢 borç yok. 🟡 kilidi boş kesilmiş iş açıklanmış ama geçmiş teslimi belirsiz.
🔴 açıklanmamış eski inflight, fail veya okunamayan kaynak; kaynağa erişmeden yeşile çevirme.

Düzeltme kapsamı yetkiliyse `--reconcile` yalnız kilidi boş,24 saatten eski inflight'ı
özgün durumunu koruyarak `interrupted` yapar. Çalışan sahip/kilit korunur; kayıt silinmez.
`legacy-append-unknown` geçmişte günlük yazılıp yazılmadığı kanıtlanamıyor demektir.
`--retry <64-haneli-oturum-sha256>` yalnız `flush-requests/` içinde yakalanmış istekle
çalışır; state dosya adındaki tam hash kullanılır. Eski isteksiz işlere tahminle reason,
runner veya olay zamanı verilmez. Kaynak hash'i değiştiyse yeniden deneme durur;
yeniden deneme model çağrısı ve günlük yazımı yapabilir, salt-okunur kontrol değildir.

Yeni günlük teslimleri hash işaretçisiyle idempotenttir; atomik gün terfisi ve kalıcı
kilit yarım yazımın ikinci kayıt gibi kalmasını önler. Append sonrası durum hatası
`state-finalization-failed` olarak ayrılır.12:50 örneğindeki gibi host erişimi yoksa
başka oturumun başarılı kaydını kurtarma kanıtı sayma.

## Rapor formatı

Tüm kontroller bittikten sonra tek tablo bas:

```
| Kontrol | Durum | Bulgu |
| --- | --- | --- |
| Hook dosyaları | 🟢 | dördü de yerinde ve çalıştırılabilir |
| settings.json bağlantısı | 🟢 | dört olay da bağlı |
| Özyineleme koruması | 🟢 | hepsinde var |
| python3 ve model CLI | 🟢 | python3 3.13.7, claude var |
| python3-missing işareti | 🟢 | işaret yok |
| Günlük log tazeliği | 🟡 | son log 51 saat önce |
| Derleme durumu | 🔴 | last_status fail:timeout |
| Sağlık kayıtları | 🔴 | dün compile hatası |
| Bilgi indeksi | 🟢 | 42 satır |
| Git | 🟢 | repo var, 3 dosya kaydedilmemiş |
| Sürüm | 🟢 | 1.0.0 |
| Kurallar | 🟢 | var, 24 satır |
| Kanca parça bütünlüğü | 🟢 | SessionStart kurallar/hafiza birer; diğer olaylar birer |
| Sır yedeği artığı | 🟢 | temiz |
| Kaynak ve bölüm limitleri | 🟢 | seçilen çekirdek sınırın altında; limit okunabilir |
| Teslim kırpılması | 🟡 | bölüm/bütçe ayrı; eski kayıtlarda bölüm bilgisi bilinmiyor |
| Sessiz hata sayaçları | 🟢 | kayıt yok |
| Aktarım borcu | 🟡 | kesilmiş iş açıklanmış; kaynak/teslim uyarısı korunuyor |
```

Tablodan sonra sadece 🔴 satırlar için "Düzeltme:" ile başlayan birer satır yaz, komutu da ver.
Sonra tek cümlelik hüküm: örneğin "Beyin ayakta ama derleyici iki gündür takılı, önce onu çöz."
Her şey yeşilse hüküm de kısa olsun: "Beyin sağlıklı, yapılacak bir şey yok."
