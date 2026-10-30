"""Özetleyici ve derleyiciye giden güvenilmeyen metinde talimat biçimini bozar.

Oturum dökümü ve günlük, model istemine "VERİ" bloğu olarak girer. İçerikteki
`SYSTEM:` gibi bir rol başlığı, sahte bir `--- END UNTRUSTED ... ---` sınırı ya da
tur metninin ortasındaki sahte `**User:**` satırı modele talimat veya kullanıcı
kararı gibi görünebilir. Burada metin silinmez: etiket korunur, yalnız biçim
`[MASKE:...]` ile kırılır; özet bilgiyi kaybetmez (27.10.2026 denetimi, dalga 2).
"""

from __future__ import annotations

import re

# Satır başındaki rol/talimat başlığı. `[ \t]*`, `\s*`in boş satırları yutmasını önler.
TALIMAT_BASLIGI = re.compile(
    r"(?im)^[ \t]*(?P<etiket>"
    r"UNTRUSTED[_ -]?DIRECTIVE|DIRECTIVE|INSTRUCTIONS?|SYSTEM|ASSISTANT|USER|HUMAN|DEVELOPER|"
    r"S[İI]STEM|TAL[İI]MAT|KOMUT|IGNORE\s+(?:ALL|ANY|PREVIOUS)"
    r")[ \t]*[:：]"
)
# İstemdeki veri bloğu sınırlarının taklidi.
SINIR_TAKLIDI = re.compile(r"(?im)^[^\n]*-{3}[ \t]*(?:BEGIN|END)[ \t]+UNTRUSTED\b[^\n]*$")
# flush.format_turns tur başlığının tur metni içindeki taklidi.
ROL_TAKLIDI = re.compile(r"(?m)^[ \t]*\*\*(?P<rol>User|Assistant):\*\*")


def maskele(metin: str) -> tuple[str, int]:
    """Talimat başlıklarını ve sınır taklitlerini maskele; (metin, adet) döner."""
    metin, sinir = SINIR_TAKLIDI.subn("[MASKE:sinir]", metin)
    metin, baslik = TALIMAT_BASLIGI.subn(
        lambda m: f"[MASKE:talimat:{' '.join(m.group('etiket').split())}]", metin
    )
    return metin, sinir + baslik


def rol_maskele(metin: str) -> tuple[str, int]:
    """Tek bir turun metnindeki sahte tur başlıklarını maskele."""
    return ROL_TAKLIDI.subn(lambda m: f"[MASKE:rol:{m.group('rol')}]", metin)
