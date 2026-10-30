---
created: {{BUGUN}}
type: memory
status: baglayici
tags: [hafiza, kurallar, vault, baglanti]
id: vault-not-baglanti-standardi
title: Vault Bağlantı Standardı
---

# Vault Bağlantı Standardı

> ⬆️ [[kimlik-cekirdegi]] · Bu dosya **bağlayıcıdır**: yeni not açarken ve mevcut notu düzenlerken uygulanır.

## Temel kural

**Her notun bir üstü, bir de komşuları vardır.** Üst = hiyerarşide nereye ait olduğu.
Komşu = onunla birlikte anlam kazandığı diğer notlar. İkisi farklı yerde yazılır.

## Adlandırma

- Asistanın açtığı yeni dosya ve klasör adları ASCII kebab-case olur (`proje-durum-ozeti.md`).
  Kullanıcının kendi notlarının adlarına dokunulmaz.
- İnsan tarafından okunan tarihler `GG.AA.YYYY`.
- Bir notun adı değişirse wikilinkler ve breadcrumb'lar aynı değişiklikte güncellenir.

## Şema

### 1. Breadcrumb — H1 başlığın hemen altında, tek satır

```
> ⬆️ [[üst-not]] · <bir cümlelik konum bilgisi>
```

| Not tipi | Üstü |
| --- | --- |
| Bölüm indeksi | [[kontrol-paneli]] |
| Proje notu | [[projeler-genel-bakis]] |
| Proje alt dosyası | o projenin `-proje-durum-ozeti` notu |
| Hedef notu | [[hedefler-genel-bakis]] |
| Hafıza dosyası | [[kimlik-cekirdegi]] |
| Arşiv notu | [[arsiv-genel-bakis]] |
| `550-derlenmis-bilgi-tabani/` notu | [[bilgi-tabani-indeksi]] — makine yazımı |

### 2. `## İlgili` — dosyanın sonunda, gerekçeli liste

```
## İlgili

- [[not-adı]] — neden ilgili olduğu, tek satır
```

**Gerekçesiz bağlantı yazılmaz.** Okuyan kişi tıklamadan önce neden tıklayacağını bilmeli.
İlişkiye 10 üzerinden puan ver; 7'nin altı yazılmaz (tematik benzerlik bağlantı sebebi değildir).

### 3. Gövde içi bağlantı

Metinde bir nottan bahsedilince `[[wikilink]]` kullanılır. Kod, komut ve Markdown olmayan dosyalar
(`.html`, `.pdf`) backtick içinde kalır.

## Simetri

Yatay bağlantılar çift yönlüdür: A, B'ye bağlıysa B de A'ya bağlanır. İstisna: kontrol paneli, bölüm
indeksleri ve oturum kayıtları (son-oturum-ozetleri, gunluk-gozlemleri, aktif-konu-takibi) yalnız bahseder,
geri bağlantı beklemez.

## Ne bağlanmaz

- **`550-derlenmis-bilgi-tabani/` elle düzenlenmez.** Orayı `.beyin/scripts/compile.py` yazar; oraya elle
  bağlantı eklemek bir sonraki derlemede silinebilir. Vault'tan oraya bağlantı verilir, tersi derleyicinin işidir.
- **`800-gunluk-oturum-kayitlari/` içine bağlantı yazılmaz.** Onlar oturum kaydı; kaynak olarak gösterilir.

## Yeni not açarken

[[yeni-not-sablonu]] breadcrumb ve `## İlgili` iskeletini içerir. Bağlanacak yer bulamıyorsan not
muhtemelen henüz olgun değil — [[hizli-not-yakalama]]'ya yaz.

## İlgili

- [[davranis-kurallari]] — davranış kuralları; bu dosya onların vault yapısı üzerindeki karşılığı.
