---
name: haftalik-ozet
description: Vault'un kendi kayıtlarından (thread'ler, proje frontmatter'ı, günlük loglar, git log, hedef tarihleri) deterministik bir haftalık özet üretir. "haftalık özet", "bu hafta ne yaptık", "haftalık rapor" dendiğinde kullan.
---

# Haftalık Özet

Kontrol panelinin "Bu hafta" bölümü elle yazılınca tazeliğini kaybeder. Bu skill aynı bilgiyi
`.beyin/scripts/haftalik_ozet.py` ile vault'un kendi kayıtlarından her seferinde yeniden üretir —
LLM çağrısı yok, tamamen deterministik.

## Nasıl çalışırsın

1. Vault kökünde çalıştır:

```bash
python3 .beyin/scripts/haftalik_ozet.py
```

Varsayılan pencere son 7 gündür; `--gun N` ile değiştirilir, `--bitis GG.AA.YYYY` ile
pencerenin son günü sabitlenir (tekrar üretilebilirlik için, örn. geçmiş bir haftayı sormak).

2. Çıktı Türkçe Markdown olarak stdout'a basılır: açık thread'ler (🟡/🔴), bu pencerede
   güncellenen thread'ler, bayat aktif projeler (14 günden uzun süredir dokunulmamış),
   günlük oturum sayıları, git commit özeti ve `200-hedefler/` içindeki 14 gün ufkundaki
   yaklaşan tarihler.

3. Script'in çıktısının üstüne **asistan olarak 3-5 satırlık bir yorum ekle**: hangi bulgu dikkat
   ister, hangisi normal, kullanıcının bir karar vermesi gereken bir şey var mı. Script ham
   veriyi verir, yorumu sen yaparsın — ikisini karıştırma.

4. Kullanıcı kalıcı bir kayıt isterse (`--yaz`):

```bash
python3 .beyin/scripts/haftalik_ozet.py --yaz
```

Bu, `100-komuta-merkezi/haftalik-ozet.md` dosyasını (tek dönen dosya, üstüne yazılır) günceller.
`.beyin/scripts/vault_write.py` bulunuyorsa kilitli/atomik yazım için onu kullanır, yoksa kendi
atomik yazımına (tmp + `os.replace`) düşer. Breadcrumb ve `## İlgili` bölümünü
[[vault-not-baglanti-standardi]]'na uygun kendisi üretir; elle düzenleme.

5. Makine tüketimi gerekiyorsa `--json`; ek repo (ör. bir proje kodunun kendi git geçmişi)
   dahil etmek için `--depo /path/to/repo` (tekrarlanabilir).

## Sınırlar

- **`850-hafiza/aktif-konu-takibi.md` dosyasını asla düzenlemez, sadece okur.** Thread'leri
  güncellemek asistanın işi, script'in değil.
- Script salt okunurdur; `100-komuta-merkezi/haftalik-ozet.md` dışında hiçbir dosyaya yazmaz.
- Git log okunamazsa (repo yok, `git` bulunamadı) o depo için "ölçülemedi" notu düşer, script
  çökmez.
- "Bayat" eşiği sabit 14 gün; script'in kendi kodunda `BAYAT_ESIK_GUN` sabiti.

## İlgili

- [[aktif-konu-takibi]] — thread parsing'in kaynağı
- [[kontrol-paneli]] — "Bu hafta" bölümünün elle bakımı yerine bu skill kullanılabilir
- [[vault-not-baglanti-standardi]] — `--yaz` çıktısının uyduğu bağlantı şeması
