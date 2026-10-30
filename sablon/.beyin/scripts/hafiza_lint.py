#!/usr/bin/env python3
"""Hafıza lint'i: hafıza dosyalarının içeriğini salt-okur denetler.

beyin-doktor altyapıya (hook, derleme, kırık bağlantı) bakar; bu betik içeriğe bakar:
Kurallar bölümü dışına düşmüş kural, tekrar eden blok, bayat ya da arşivlenmiş projeye ait konu,
süresi dolmuş geçerlilik işareti. Hiçbir dosyayı değiştirmez. HATA varsa çıkış kodu 1.

Geçerlilik işareti: kural maddesine ya da konu bloğuna `[geçerli: 10.11.2026]` (tarih, o gün dahil)
ya da `[geçerli: Kullanıcı "bitti" deyene kadar]` (koşul) yazılır. Tarih geçince UYARI verilir;
koşullar makineyle denetlenemez, `--kosullar` ile BİLGİ olarak listelenir.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys

from select_threads import normalize

VAULT = Path(__file__).resolve().parents[2]
HAFIZA = '850-hafiza'
KURALLAR = HAFIZA + '/davranis-kurallari.md'
KONULAR = HAFIZA + '/aktif-konu-takibi.md'
CEKIRDEK = HAFIZA + '/calisma-cekirdegi.md'
ARSIV = '900-arsiv'
AZAMI_KONU = 15
BAYAT_ACIK_GUN = 21
BAYAT_KAPALI_GUN = 14
TARIH = re.compile(r'\b(\d{2})\.(\d{2})\.(\d{4})\b')
KONU_BOLUMLERI = {'Active Threads', 'Closed Threads', 'İlgili'}
GECERLI = re.compile(r'\[geçerli:\s*([^\]]*?)\s*\]')


def satirlar(path):
    """(satır no, satır) çiftleri; ``` çitli kod bloklarındaki örnek başlıklar atlanır."""
    cit = False
    for no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if line.lstrip().startswith('```'):
            cit = not cit
        elif not cit:
            yield no, line


def bulgu(seviye, kod, yol, satir, mesaj):
    return {'seviye': seviye, 'kod': kod, 'yol': yol, 'satir': satir, 'mesaj': mesaj}


def yetim_kurallar(root):
    """Yetkili kurallar `## Kurallar` bölümüdür; dışına düşen madde göreve göre okunurken de atlanır."""
    path = root / KURALLAR
    if not path.is_file():
        return []
    out, bolum = [], None
    for no, line in satirlar(path):
        if line.startswith('## '):
            bolum = line[3:].strip()
        elif line.startswith('- **kural') and bolum != 'Kurallar':
            out.append(bulgu('HATA', 'yetim-kural', KURALLAR, no,
                             f"kural `## {bolum}` altında, Kurallar bölümünün dışında; `## Kurallar` içine taşı"))
    return out


def yapisal(root):
    out = []
    for path in sorted((root / HAFIZA).glob('*.md')):
        rel = str(path.relative_to(root))
        gorulen = {}
        ilgili = []
        for no, line in satirlar(path):
            if not re.match(r'#{2,3} ', line):
                continue
            baslik = line.strip()
            if baslik == '## İlgili':
                ilgili.append(no)
            elif baslik in gorulen:
                out.append(bulgu('HATA', 'tekrar-baslik', rel, no, f'aynı başlık {gorulen[baslik]}. satırda da var: {baslik[:70]}'))
            else:
                gorulen[baslik] = no
        if len(ilgili) > 1:
            out.append(bulgu('HATA', 'cift-ilgili', rel, ilgili[1], f"{len(ilgili)} adet `## İlgili` bölümü var"))
    return out


def aktif_konu_bloklari(path):
    """`## Active Threads` altındaki konular: [satır no, başlık, gövde satırları]."""
    bloklar, bolum = [], None
    for no, line in satirlar(path):
        if line.startswith('## '):
            bolum = line[3:].strip()
        elif line.startswith('### Thread:') and bolum == 'Active Threads':
            bloklar.append([no, line[len('### Thread:'):].strip(), []])
        elif bloklar and bolum == 'Active Threads':
            bloklar[-1][2].append(line)
    return bloklar


def kural_bloklari(path):
    """`## Kurallar` altındaki üst düzey maddeler: (satır no, madde satırı, tüm metin)."""
    out, bolum, blok = [], None, None
    for no, line in satirlar(path):
        if line.startswith('## '):
            bolum, blok = line[3:].strip(), None
        elif bolum != 'Kurallar':
            continue
        elif line.startswith('- '):
            blok = (no, line, [line])
            out.append(blok)
        elif blok and line.startswith((' ', '\t')):
            blok[2].append(line)
        elif line.strip():
            blok = None
    return [(no, ilk, '\n'.join(metin)) for no, ilk, metin in out]


def konular(root, bugun):
    path = root / KONULAR
    if not path.is_file():
        return []
    arsivli = {normalize(p.name.replace('-', ' ')): p.name for p in (root / ARSIV).iterdir() if p.is_dir()} \
        if (root / ARSIV).is_dir() else {}
    out, bloklar = [], aktif_konu_bloklari(path)
    for no, line in satirlar(path):
        if line.startswith('## ') and line[3:].strip() not in KONU_BOLUMLERI:
            out.append(bulgu('UYARI', 'basibos-bolum', KONULAR, no,
                             f'konu dosyasında beklenmeyen bölüm: {line[3:].strip()[:60]}'))
    if len(bloklar) > AZAMI_KONU:
        out.append(bulgu('UYARI', 'konu-sayisi', KONULAR, bloklar[0][0],
                         f'{len(bloklar)} aktif konu var; hedef {AZAMI_KONU} ve altı'))
    for no, baslik, govde in bloklar:
        metin = '\n'.join(govde)
        durum = re.search(r'^\*\*Status:\*\*\s*(.*)$', metin, re.M)
        tarihler = [d for d in (_tarih(m) for m in TARIH.finditer(baslik + '\n' + metin)) if d and d <= bugun]
        son = max(tarihler) if tarihler else None
        if not durum:
            out.append(bulgu('UYARI', 'durumsuz-konu', KONULAR, no, f'**Status:** satırı yok: {baslik[:60]}'))
        else:
            isaret = durum.group(1).strip()[:1]
            gun = (bugun - son).days if son else None
            if isaret == '🟢' and gun is not None and gun > BAYAT_KAPALI_GUN:
                out.append(bulgu('UYARI', 'kapanmis-konu', KONULAR, no,
                                 f'🟢 ve {gun} gündür değişmedi; arşivleyici tanımıyor, ⚪ ya da "tamamlandı" yap: {baslik[:60]}'))
            elif isaret != '🟢' and gun is not None and gun > BAYAT_ACIK_GUN:
                out.append(bulgu('UYARI', 'bayat-konu', KONULAR, no, f'{gun} gündür değişmedi: {baslik[:60]}'))
        baslik_n = normalize(baslik)
        for ad, klasor in arsivli.items():
            if ad and re.search(rf'\b{re.escape(ad)}\b', baslik_n):
                out.append(bulgu('UYARI', 'arsivli-proje', KONULAR, no,
                                 f'{ARSIV}/{klasor} arşivde ama konu açık: {baslik[:60]}'))
    return out


def gecerlilik(root, bugun, kosullar=False):
    """`[geçerli: ...]` işaretleri: dolmuş tarih UYARI, bozuk tarih UYARI, koşul isteğe bağlı BİLGİ."""
    ogeler = []
    for yol in (KURALLAR, CEKIRDEK):
        if (root / yol).is_file():
            ogeler += [(yol, no, 'kuralı', ilk, metin) for no, ilk, metin in kural_bloklari(root / yol)]
    if (root / KONULAR).is_file():
        ogeler += [(KONULAR, no, 'konuyu', baslik, baslik + '\n' + '\n'.join(govde))
                   for no, baslik, govde in aktif_konu_bloklari(root / KONULAR)]
    out = []
    for yol, no, tur, ozet, metin in ogeler:
        ozet = ozet.lstrip('- ').replace('**', '')[:60]
        for m in GECERLI.finditer(metin):
            deger = m.group(1)
            if re.fullmatch(r'[\d.]+', deger):
                eslesme = re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', deger)
                gun = _tarih(eslesme) if eslesme else None
                if gun is None:
                    out.append(bulgu('UYARI', 'gecerlilik-bicim', yol, no,
                                     f'`[geçerli: {deger}]` geçerli bir GG.AA.YYYY tarihi değil: {ozet}'))
                elif gun < bugun:
                    out.append(bulgu('UYARI', 'gecerlilik-doldu', yol, no,
                                     f'geçerlilik {deger} tarihinde doldu ({(bugun - gun).days} gün önce); '
                                     f'{tur} güncelle, kapat ya da süreyi uzat: {ozet}'))
            elif not deger:
                out.append(bulgu('UYARI', 'gecerlilik-bicim', yol, no, f'`[geçerli: ]` boş: {ozet}'))
            elif kosullar:
                out.append(bulgu('BİLGİ', 'gecerlilik-kosul', yol, no, f'koşul: {deger}: {ozet}'))
    return out


def _tarih(m):
    try:
        return datetime.strptime(m.group(0), '%d.%m.%Y').date()
    except ValueError:
        return None


def denetle(root=VAULT, bugun=None, kosullar=False):
    bugun = bugun or date.today()
    return [*yetim_kurallar(root), *yapisal(root), *konular(root, bugun),
            *gecerlilik(root, bugun, kosullar)]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', default=str(VAULT))
    p.add_argument('--json', action='store_true')
    p.add_argument('--kosullar', action='store_true', help='koşullu geçerlilik işaretlerini de listele')
    a = p.parse_args(argv)
    bulgular = denetle(Path(a.root), kosullar=a.kosullar)
    if a.json:
        print(json.dumps(bulgular, ensure_ascii=False, indent=1))
    else:
        for b in bulgular:
            print(f"{b['seviye']:5} {b['kod']:14} {b['yol']}:{b['satir']}  {b['mesaj']}")
        hata = sum(b['seviye'] == 'HATA' for b in bulgular)
        print(f"{hata} hata, {sum(b['seviye'] == 'UYARI' for b in bulgular)} uyarı")
    return 1 if any(b['seviye'] == 'HATA' for b in bulgular) else 0


if __name__ == '__main__':
    sys.exit(main())
