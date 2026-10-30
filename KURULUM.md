# KURULUM.md — İkinci Beyin Kurulum Rehberi (AI için)

> Sen bu repoyu indiren yapay zekâ asistanısın: **Codex** ya da **Claude Code**. İkisi de desteklenir. Karşındaki kişi kendi
> Obsidian vault'unun üstüne, oturumlar arasında **kendiliğinden hatırlayan** bir ikinci beyin
> kurmak istiyor. Bu dosya eksiksiz kurulum talimatıdır. Baştan sona bir kez oku, sonra
> aşamaları sırayla uygula. Başka bağlama ihtiyacın yok.

---

## Fikir (kullanıcıya kendi cümlelerinle, kısaca anlat)

AI sohbetleri her oturumda kullanıcıyı unutur. Bu sistem bunu düzeltir: Obsidian vault'u ortak
hafıza olur, Codex ya da Claude Code onu sürer. Hafıza bir disiplin değil, **mekanizmadır**:

1. **Oturum başı** — hook, son oturum özetini, açık konuları, kuralları ve son gözlemi bağlama koyar.
2. **Oturum sonu / sıkıştırma öncesi** — hook arka planda konuşmayı özetler (Codex'te `codex exec`,
   Claude Code'da `claude -p` haiku),
   `800-gunluk-oturum-kayitlari/GG.AA.YYYY.md` dosyasına yazar.
3. **Akşam (18:00 sonrası ilk fırsatta)** — derleyici günlük logları `550-derlenmis-bilgi-tabani/`
   altında birbirine bağlı kavram makalelerine çevirir.
4. **İlişkisel katman** — asistan anlamlı oturum sonunda `850-hafiza/` dosyalarını (son oturum,
   aktif konular, gözlemler, kurallar) kendisi günceller. Kullanıcı düzeltme yaptığında kural yazar.

API anahtarı gerekmez; özetleyici ve derleyici o oturumu açan aracın mevcut aboneliğiyle (ChatGPT/Codex
ya da Claude) çalışır. Hangi araçla açılırsa onu kullanır.

---

## Senin için kurallar (her şeyden önce)

1. **Türkçe konuş.** Kısa satırlarla ne yaptığını söyle: "Vault'u inceliyorum…", "Hook'ları bağlıyorum…".
2. **Asla yok etme.** Kullanıcının mevcut notlarını taşıma, yeniden adlandırma, silme, düzenleme.
   Hedefte zaten olan bir dosya varsa üzerine yazma; göster ve sor. `araclar/kur.py` bunu zaten
   garanti eder; elle kopyalama yapma.
3. **Önce soru, sonra kurulum.** 2. aşamadaki soruları sormadan hedef vault'a hiçbir şey yazma.
4. **Her `{{YER_TUTUCU}}` doldurulur.** Kurulumdan sonra hiçbir dosyada `{{...}}` kalmaz.
5. **Her aşamayı doğrula**, sonra devam et. Sonunda ilk çalıştırma raporunu ver.
6. **İsteğe bağlı adımda takılma.** Yedek zamanlayıcısı ya da remote kurulamazsa not al, söyle, devam et.
7. **Sırları koru.** `.claude/settings.local.json`, `.env` gibi dosyalar asla commit edilmez.

---

## AŞAMA 0: Platform ve ön koşullar

Önce ortamı tespit et (`uname -s`, `$WSL_DISTRO_NAME`, PowerShell'de `$env:OS`):

- **Linux, macOS, WSL** → devam.
- **Yerel Windows (WSL'siz)** → hook'lar bash ile yazıldığı için desteklenmiyor. Kullanıcıya WSL
  kurmasını öner (`wsl --install`), vault'u WSL içinden açmasını anlat ve dur.

Ön koşulları kontrol et:

```bash
for k in git python3 codex claude bash; do command -v $k >/dev/null && echo "$k: var" || echo "$k: YOK"; done
python3 -c 'import sys; print("python", sys.version.split()[0], "OK" if sys.version_info >= (3, 10) else "ESKİ (3.10+ gerekli)")'
```

Eksik olan varsa kurulum komutunu göster ve **onay alarak** kur (macOS: `brew install git python`;
Debian/Ubuntu: `sudo apt install git python3`; Arch: `sudo pacman -S git python`). `codex` ve `claude`'dan
**en az biri** zorunlu (kullanıcının kullandığı araç). Codex için `codex login` ile giriş yapılmış
olmalı (`codex login status`). Yoksa resmi kurulumu öner: `npm install -g @openai/codex`.

---

## AŞAMA 1: Repoyu geçici bir yere al

Bu repo zaten indirildiyse yolunu not et (`KURULUM.md`'nin bulunduğu klasör = `REPO`). Değilse:

```bash
REPO=$(mktemp -d)/ikinci-beyin && git clone https://github.com/ba2han-orhan/ikinci-beyin.git "$REPO"
```

---

## AŞAMA 2: Soru-cevap (zorunlu kişiselleştirme)

**Önce sor:** "Profil anketini (`araclar/profil-anketi.html`) doldurdun mu?" Doldurduysa
`profil.json` yolunu al, 1–5. soruları atla (cevaplar dosyada), yalnız 6–10'u sor ve aşama 4'te
`--profil <yol>` kullan. Doldurmadıysa anketi tarayıcıda açmasını öner (6 dakika, ayrıntılı
kişiselleştirme); istemezse aşağıdaki soruları sor.

Soruları **tek tek** ya da küçük gruplar hâlinde, gündelik dille sor. Her sorunun neden önemli
olduğunu yarım cümleyle söyle. Cevapları bir yere not et; sonunda özetleyip onay al.

| # | Soru | Yer tutucu | Not |
| --- | --- | --- | --- |
| 1 | "Sana nasıl hitap edeyim, adın ne?" | `{{KULLANICI_ADI}}` | |
| 2 | "Asistanının bir adı olsun mu? (ör. Echo, Atlas, Nova)" | `{{ASISTAN_ADI}}` | İstemezse `Asistan` |
| 3 | "Kendini 1-2 cümleyle anlatır mısın? Ne iş yapıyorsun, neyle uğraşıyorsun?" | `{{KULLANICI_BAGLAM}}` | Hafızanın ilk çapası |
| 4 | "Şu sıralar en çok hangi alanlara odaklanıyorsun?" | `{{ODAK_ALANLARI}}` | Virgülle liste |
| 5 | "Nasıl bir konuşma tarzı istersin?" Seçenek sun: *sıcak ve direkt* · *kuru ve iş odaklı* · *samimi ve esprili* · *kendi tarifin* | `{{TON}}` | |
| 6 | "Obsidian vault'un nerede? (klasör yolu)" | hedef yol | Yolu doğrula: `ls`, `.obsidian/` var mı |
| 7 | "Beyni mevcut vault'unun **içine** mi kuralım (önerilen: notlarına dokunmadan yanına numaralı klasörler eklenir), yoksa **ayrı yeni** bir vault mu?" | hedef yol | Ayrıysa yeni klasör yolu iste |
| 8 | "Vault'un adı ne olsun?" | `{{VAULT_ADI}}` | Varsayılan: klasör adı |
| 9 | "Beyni hangi araçla kullanacaksın: Codex, Claude Code, ikisi?" | — | Codex ise aşama 4'te `--codex` |
| 10 | "Notlarını otomatik yedekleyelim mi? Özel (private) bir GitHub reposu var mı ya da açalım mı?" | — | Aşama 6 |

`{{BUGUN}}` = `date +%d.%m.%Y`. `{{MEVCUT_NOTLAR_SATIRI}}` aşama 3'te üretilir.

---

## AŞAMA 3: Mevcut vault'u incele (salt okunur)

```bash
HEDEF="<cevap 6/7>"
ls -la "$HEDEF"; find "$HEDEF" -maxdepth 1 -mindepth 1 -not -name '.*' | head -50
find "$HEDEF" -name '*.md' -not -path '*/.*' | wc -l
ls -la "$HEDEF/.claude" 2>/dev/null; cat "$HEDEF/CLAUDE.md" 2>/dev/null | head -20
git -C "$HEDEF" status -s 2>/dev/null | head -5
```

Kullanıcıya kısa özet ver: kaç not var, hangi üst klasörler var, çakışma riski olan şeyler
(`CLAUDE.md`, `.claude/settings.json`, `000-…`/`850-…` gibi aynı adlı klasörler, mevcut git deposu).

- Vault'ta **zaten `CLAUDE.md` varsa**: kurulum onu atlar. Kurulumdan sonra şablondaki
  `REPO/sablon/CLAUDE.md` içeriğini kullanıcının dosyasının **sonuna** eklemeyi öner; onay alırsan ekle.
- Kullanıcının mevcut üst klasörlerinden tek satırlık bir yönlendirme yaz ve `MEVCUT_NOTLAR_SATIRI`
  yap. Örnek:
  `Kullanıcının mevcut notları: \`Dersler/\`, \`Fikirler/\`, \`Günlük/\`. Okumak serbest; taşımak, yeniden adlandırmak ve düzenlemek onayla.`
  Mevcut not yoksa boş bırak.

---

## AŞAMA 4: Kur

Değerleri JSON'a yaz (geçici dizine, vault'un dışına):

```bash
cat > /tmp/beyin-degerler.json <<'EOF'
{
  "VAULT_ADI": "...",
  "ASISTAN_ADI": "...",
  "KULLANICI_ADI": "...",
  "KULLANICI_BAGLAM": "...",
  "ODAK_ALANLARI": "...",
  "TON": "...",
  "BUGUN": "GG.AA.YYYY",
  "MEVCUT_NOTLAR_SATIRI": "..."
}
EOF
```

Önce kuru koşu, planı kullanıcıya göster:

```bash
python3 "$REPO/araclar/kur.py" --hedef "$HEDEF" --degerler /tmp/beyin-degerler.json --kuru
```

Anket varsa `--profil profil.json` ekle; `--degerler` dosyasına yalnız `VAULT_ADI` ve
`MEVCUT_NOTLAR_SATIRI` yazman yeter (elle verilen değer anketi ezer). Kurulum ayrıca
`850-hafiza/kullanici-profili.md` yazar; asistan ilk oturumda bu notu projelere, hedeflere ve
kurallara dağıtır.

Onay gelince uygula. Kullanıcı **Codex** kullanıyorsa (cevap 9) `--codex` ekle:

```bash
python3 "$REPO/araclar/kur.py" --hedef "$HEDEF" --degerler /tmp/beyin-degerler.json --codex
```

`--codex` ne yapar: Codex proje klasöründeki hook'ları okumadığı için beyin hook'larını global
`~/.codex/hooks.json` dosyasına mutlak yollarla ekler (önce `hooks.json.beyin-oncesi` yedeği alır,
kullanıcının diğer hook'larına dokunmaz). Hook'lar vault dışındaki Codex oturumlarında kendiliğinden
susar. Codex `AGENTS.md`'yi okur; kurulum onu `CLAUDE.md`'ye bağlantı olarak açar, skill'leri de
`.agents/skills` altına bağlar. Vault taşınırsa `python3 .beyin/scripts/codex_kur.py` yeniden çalıştırılır.

Script ne yapar: şablonu kopyalar (hedefte olanı **atlar**), yer tutucuları doldurur, mevcut
`.claude/settings.json` varsa hook'ları birleştirir (önce `settings.json.kurulum-oncesi` yedeği
alır), skill'leri `.claude/skills` altına bağlar, hook'ları çalıştırılabilir yapar. Çıktının sonunda
`YER TUTUCU KONTROLÜ: temiz` görmelisin. `ATLANAN` listesi boş değilse kullanıcıya göster; atlanan
dosya bir hafıza dosyasıysa (`850-hafiza/…`) birleştirmeyi elle öner, zorla yazma.

Kurulan yapı:

| Klasör | Ne için |
| --- | --- |
| `000-gelen-kutusu/` | Ham fikirler; mesajın sonuna ` 000` yazmak buraya kaydeder |
| `100-komuta-merkezi/` | Kontrol paneli (ana sayfa), haftalık özet |
| `200-hedefler/` | Hedefler ve tarihler |
| `300-projeler/` | Her proje için `<proje>-proje-durum-ozeti.md` |
| `500-kalici-bilgi/` | İnsan yazımı kalıcı notlar |
| `550-derlenmis-bilgi-tabani/` | Makinenin derlediği kavramlar — **elle düzenlenmez** |
| `600-araclar-ve-kaynaklar/` | Araçlar, kaynaklar, beyin bileşen listesi |
| `800-gunluk-oturum-kayitlari/` | Otomatik günlük oturum özetleri |
| `850-hafiza/` | Kimlik, kurallar, aktif konular, son oturumlar, gözlemler, hata defteri |
| `900-arsiv/` | Biten işler, eski hafıza girdileri |
| `950-sablonlar/` | Yeni not şablonu |
| `.beyin/` | Hook'lar, script'ler, skill'ler (Obsidian gizli klasörleri göstermez) |

---

## AŞAMA 5: Doğrula

Vault kökünde:

```bash
cd "$HEDEF"
export CLAUDE_PROJECT_DIR="$PWD"
# 1) Oturum başı hook'u bağlam üretiyor mu?
echo '{"session_id":"kurulum-testi","cwd":"'"$PWD"'"}' | .beyin/hooks/session-start.sh hafiza | head -c 300; echo
.beyin/hooks/session-start.sh kurallar </dev/null | head -c 200; echo
# 2) Hafıza dosyaları biçim olarak temiz mi?
python3 .beyin/scripts/hafiza_lint.py
# 3) Hook kayıtları tam mı? (Claude Code ayarı)
python3 .beyin/scripts/context_health.py
# 3b) Codex kullanıyorsa: beyin hook'ları global dosyada mı?
grep -c '/.beyin/hooks/' ~/.codex/hooks.json 2>/dev/null
# 4) 000 yakalama çalışıyor mu? (test girdisini sonra sil)
echo '{"session_id":"kurulum-testi","cwd":"'"$PWD"'","prompt":"kurulum testi 000"}' | .beyin/hooks/prompt-counter.sh
tail -4 000-gelen-kutusu/hizli-not-yakalama.md
```

Codex için 1'i `env -u CLAUDE_PROJECT_DIR` ile de dene (Codex bu değişkeni vermez; çıktıda
`[Hafıza: Kurallar]` da olmalı). Beklenen: 1'de `[Hafıza: Son Oturum]` içeren JSON, 2'de `0 hata`,
3'te dört olay `ok`, 3b'de `8`, 4'te
"kaydedildi" ve dosyanın sonunda alıntı. 4'teki test girdisini (`### … · Hızlı yakalama` bloğunu)
`hizli-not-yakalama.md`'den sil. Ardından test durum dosyalarını temizle:
`rm -f .beyin/scripts/.state/*kurulum* .beyin/scripts/.state/prompt_count.* .beyin/scripts/.state/session_start_time.*`

İsteğe bağlı uçtan uca deneme (bir haiku çağrısı harcar): kısa sahte bir transcript ile
`python3 .beyin/scripts/flush.py --hook-input <dosya>` çalıştırıp `800-gunluk-oturum-kayitlari/`
altında günlük oluştuğunu gör. Hook girdisi biçimi: `{"session_id","transcript_path","cwd","hook_event_name":"SessionEnd"}`.
Bu adımı yaptıysan oluşan günlüğü sil, yoksa derleyici sahte veriyi bilgi tabanına işler.

---

## AŞAMA 6: Git ve yedek

Vault kullanıcının hafızası; ilk günden sürümle.

```bash
cd "$HEDEF"
git rev-parse --is-inside-work-tree 2>/dev/null || git init -q
git add -A
git diff --cached --name-only | grep -E 'settings\.local\.json|\.env$|\.bak$|\.yedek' && { git reset -q; echo "SIR DOSYASI SAHNEDE — .gitignore'u düzelt"; }
git -c user.name="$(git config user.name || echo beyin)" -c user.email="$(git config user.email || echo beyin@localhost)" \
  commit -qm "İkinci beyin kuruldu" && git log --oneline -1
```

Vault zaten bir git deposuysa ve kullanıcının kendi `.gitignore`'u varsa, şablonun `.gitignore`
satırları atlanmış olabilir; `REPO/sablon/.gitignore` içindeki satırları eksikse **ekle** (silme).

**Remote (önerilir, cevap 10 evetse):** Notlar kişisel olduğu için repo mutlaka **private** olmalı.
`gh` varsa: `gh repo create <ad> --private --source . --push`. Yoksa kullanıcıdan boş private repo
adresini iste: `git remote add origin <adres> && git push -u origin HEAD`.

**Otomatik yedek:** `.beyin/scripts/yedek.sh` değişiklik varsa commit'ler, remote varsa push'lar;
hata olursa bir sonraki oturumun başında uyarı çıkar. Zamanlayıcı (kullanıcı onayıyla):

```bash
( crontab -l 2>/dev/null; echo "0 */3 * * * \"$HEDEF/.beyin/scripts/yedek.sh\" >/dev/null 2>&1" ) | crontab -
```

macOS'ta cron'un vault klasörüne erişimi için Terminal'e "Tam Disk Erişimi" gerekebilir; olmazsa
yedeği elle çalıştırmayı (`.beyin/scripts/yedek.sh`) öğret ve devam et.

---

## AŞAMA 7: İlk çalıştırma raporu

Kullanıcıya şu biçimde kısa bir rapor ver:

```
✅ İkinci beyin kuruldu: <HEDEF>
- Asistan: <ASISTAN_ADI> · Ton: <TON>
- Mevcut notlar: <N> not, dokunulmadı
- Araç: <Codex / Claude Code / ikisi>
- Hook'lar: 7 olay bağlı (oturum başı/sonu, sıkıştırma, mesaj sayacı, bağlam bekçisi, hata yakalayıcı, yıkıcı komut bekçisi)
- Skill'ler: beyin-doktor, haftalik-ozet, hata-defteri, gecmis-import
- Yedek: <git commit / remote / zamanlayıcı durumu>
- Atlanan dosyalar: <varsa>
```

Sonra kullanım talimatını ver:

1. **Bu oturumu kapat**, terminalde vault'a geçip aracını yeniden aç: `cd "<HEDEF>" && codex`
   (ya da `claude`). Hook'lar oturum başında yüklenir.
   - **Codex:** ilk açılışta klasöre güven ver, sonra `/hooks` yaz ve beyin hook'larını
     **güvenilir işaretle**. İşaretlenmeyen hook hiç çalışmaz; bu adım atlanırsa hafıza gelmez.
   - **Claude Code:** proje hook'larını onaylamanı isterse onayla.
2. Normal konuş. Oturum sonunda özet kendiliğinden düşer; akşam bilgi tabanına derlenir.
3. Mesajın sonuna ` 000` yazarsan mesaj gelen kutusuna kaydedilir.
4. Asistan bir şeyi yanlış yaparsa "bunu böyle yapma" de; kural olarak kaydeder.
5. Faydalı komutlar: "beyin doktor" (sağlık kontrolü), "haftalık özet", "hata defterine bak",
   "eski ChatGPT/Claude geçmişimi aktar" (`gecmis-import`).
6. İlk birkaç oturumda asistan kimlik çekirdeğini (`850-hafiza/kimlik-cekirdegi.md`) seninle
   birlikte zenginleştirecek; mevcut notlarından öğrenmesini istersen açıkça söyle.

---

## Sonra: güncelleme ve kaldırma

**Güncelleme:** Repo güncellenirse yalnız mekanik katman kopyalanır; hafıza ve notlara dokunulmaz:

```bash
cd "$REPO" && git pull
for d in hooks scripts skills config; do rsync -a --exclude '.state' --exclude '__pycache__' "sablon/.beyin/$d/" "$HEDEF/.beyin/$d/"; done
```

Ardından `beyin doktor` çalıştır.

**Kaldırma:** Codex için `python3 .beyin/scripts/codex_kur.py --kaldir`. Claude için `.claude/settings.json` içindeki `.beyin/` geçen hook girdilerini sil (ya da
`settings.json.kurulum-oncesi` yedeğini geri koy), cron satırını kaldır (`crontab -e`). Klasörler
kullanıcının verisidir; silmeden önce mutlaka sor.

---

## Sorun giderme

| Belirti | Bak |
| --- | --- |
| Oturum başında hafıza gelmiyor | Araç vault kökünde mi açıldı? Codex: `~/.codex/hooks.json`'da `.beyin/hooks` var mı, `/hooks` ile güvenilir işaretlendi mi? Claude: `.claude/settings.json` hook'ları var mı? `beyin doktor` |
| Günlük log oluşmuyor | `codex`/`claude` PATH'te ve girişli mi (`codex login status`)? `.beyin/scripts/.state/last-flush.json` içindeki hata alanı |
| Derleme olmuyor | 18:00'den sonra bir oturum açılınca tetiklenir; elle: `python3 .beyin/scripts/compile.py` |
| "python3-missing" uyarısı | python3'ü PATH'e ekle, `.beyin/scripts/.state/python3-missing` dosyasını sil |
| Yıkıcı komut bekçisi bir silmeyi durdurdu | Kasıtlı: asistan neyi sileceğini söyleyip onay ister; kullanıcı onaylarsa komutu `! <komut>` ile kendisi çalıştırır |
