# Araçlar ve Kaynaklar

> ⬆️ [[kontrol-paneli]] · Kullanılan araçlar, linkler ve kaynaklar.

## Beyin bileşenleri

| Bileşen | Yer | Ne yapar |
| --- | --- | --- |
| session-start | `.beyin/hooks/session-start.sh` | Oturum başında hafızayı bağlama koyar |
| prompt-counter | `.beyin/hooks/prompt-counter.sh` | Mesaj sayar, 15'te bir hatırlatır, ` 000` yakalar |
| session-end / pre-compact | `.beyin/hooks/` | Oturum sonunda arka planda günlük özet yazar |
| flush / compile | `.beyin/scripts/` | Özetleyici ve akşam derleyicisi (Codex: `codex exec`, Claude: `claude -p`) |
| bağlam bekçisi | `.beyin/hooks/baglam-bekcisi.py` | 200k/250k bağlamda devir uyarısı |
| hata yakalayıcı | `.beyin/hooks/hata-yakalayici.py` | Başarısız araç çağrılarını hata defterine yazar |
| yıkıcı komut bekçisi | `.beyin/hooks/yikici-komut-bekcisi.py` | Geri alınamaz silme komutlarını durdurur |
| codex bağlantısı | `.beyin/scripts/codex_kur.py` | Hook'ları `~/.codex/hooks.json` dosyasına yazar / kaldırır |
| yedek | `.beyin/scripts/yedek.sh` | Vault'u git ile commit'ler, remote varsa push'lar |
| skill'ler | `.beyin/skills/` | beyin-doktor, haftalik-ozet, hata-defteri, gecmis-import |
