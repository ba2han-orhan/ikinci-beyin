---
created: {{BUGUN}}
updated: {{BUGUN}}
type: memory
tags: [hafiza, kurallar]
id: davranis-kurallari
title: Davranış Kuralları
---

# Davranış Kuralları

> ⬆️ [[kimlik-cekirdegi]] · Bağlayıcı kurallar — çalışma çekirdeği açılışta, ayrıntılar görevde okunur

Kullanıcının bu dosyaya koyduğu kurallar bağlayıcıdır. Oturum başında `calisma-cekirdegi.md` varsa onun
`## Kurallar` bölümü yüklenir; yoksa bu dosyanın `## Kurallar` ile `## Nasıl büyür` arası kullanılır.
Göreve özgü ayrıntılar buradan okunur.

## Kurallar

- **kural:** Bağlamı küçük tut: komut çıktısını baştan kısa iste (`-q`, `tail`, `grep`, `--stat`),
  uzun çıktıyı dosyaya yazıp özetini oku; dosyayı parça parça oku; aynı şeyi iki kez okuma.
  200k'dan sonra iyi bir durma noktası ara, 250k'da [[son-oturum-ozetleri]]'ne devir notu yazıp yeni oturum öner.
  **neden:** büyük bağlam her isteği pahalılaştırır ve kaliteyi düşürür.

## Nasıl büyür

Kullanıcı seni düzelttiğinde ("bunu böyle yapma", "şunu bir daha yapma") o düzeltmeyi aynı oturumda
buraya yeni bir madde olarak ekle: `- **kural (GG.AA.YYYY):** ... **neden:** ...`. Kuralı kullanıcının
kendi cümlesine yakın tut. Artık geçerli olmayan kuralı sil veya güncelle; çelişen iki maddeyi yan yana bırakma.
Süreli ya da koşullu bir kural için maddenin sonuna `[geçerli: GG.AA.YYYY]` ya da
`[geçerli: kullanıcı "bitti" deyene kadar]` yaz. `python3 .beyin/scripts/hafiza_lint.py` tarihi geçeni uyarır.

Düzeltmeler ayrıca [[hata-defteri]]'ne düşer. Tekrar eden hata için kalıcı çözüm orada önerilir,
kullanıcı onaylayınca `hata-defteri` skill'iyle uygulanır; onaysız kural yazılmaz.

## İlgili

- [[vault-not-baglanti-standardi]] — not açma ve bağlama kuralı; bu listenin yapısal tamamlayıcısı.
- [[gunluk-gozlemleri]] — bir kuralın nereden çıktığı çoğu zaman orada yazılı.
