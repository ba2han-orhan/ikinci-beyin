# İkinci Beyin — Obsidian + Claude Code hafıza sistemi

Obsidian vault'unu, oturumlar arasında kendiliğinden hatırlayan bir AI ikinci beynine çevirir.
Oturum sonunda konuşma otomatik özetlenir, akşam bilgi tabanına derlenir, bir sonraki oturumun
başında asistan kaldığınız yeri bilir. API anahtarı gerekmez; **Codex** ya da **Claude Code** aboneliğiyle çalışır.

## Kurulum

Terminalde Codex'i (ya da Claude Code'u) aç ve şunu yaz:

> Bu repoyu indir ve içindeki KURULUM.md dosyasını baştan sona okuyup benim için ikinci beynimi kur: https://github.com/ba2han-orhan/ikinci-beyin

Asistan önce birkaç soru sorar (adın, asistanın adı, vault'unun yeri, konuşma tarzı), mevcut
notlarına dokunmadan kurar ve test eder.

Gereksinimler: Linux, macOS ya da WSL · git · Python 3.10+ · Codex (`codex`) ya da Claude Code (`claude`).

## İçerik

- `KURULUM.md` — AI'ın okuyup uyguladığı kurulum rehberi
- `araclar/kur.py` — şablonu üzerine yazmadan kuran yardımcı
- `sablon/` — vault iskeleti, hafıza dosyaları, hook'lar (`.beyin/hooks`), script'ler ve skill'ler
