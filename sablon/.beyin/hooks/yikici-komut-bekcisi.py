#!/usr/bin/env python3
"""Yıkıcı komut bekçisi: geri alınamaz Bash komutlarını çalışmadan önce durdurur.

Olay: PreToolUse (Claude, matcher Bash). İstemciler bypassPermissions ile açıldığı için
izin sorusu yok; bu kanca tek fren (27.10.2026 denetimi, dalga 2). Kural: dosya silmeden
onay al. Engellenen komutu kullanıcı onaylarsa kendisi `! <komut>` ile çalıştırır. Ajanın
kancayı atlatacağı bir anahtar yok: enjekte edilmiş bir talimat da o anahtarı kullanırdı.

Durdurulanlar:
- Korunan bir kökü (/, ev, vault, Projects, ~/.claude ...) silen ya da
  kapsayan rm -r / find -delete; Projects altındaki bir projenin kökü; her .git klasörü.
- Vault içinde özyinelemeli ya da joker karakterli rm (önbellek klasörleri hariç).
- git reset --hard, git clean -f, tüm ağacı geri alan checkout/restore, zorla ya da
  silen push, git stash clear.
- mkfs, wipefs, shred, aygıta yazan dd.

/tmp altı serbesttir. Kanca kendi hatasında komutu geçirir ve kayda düşer; tüm Bash'i
kilitleyen bir bekçi, olmayan bekçiden daha kötü.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import sys
import time

sys.dont_write_bytecode = True
HOME = Path.home()
VAULT = Path(__file__).resolve().parents[2]
STATE = VAULT / ".beyin" / "scripts" / ".state"
PROJECTS = HOME / "Projects"
SERBEST = (Path("/tmp"),)

# Kendisi ya da atası silinirse geri dönüşü olmayan kökler.
KOKLER = {Path(p) for p in ("/", "/home", "/root", "/etc", "/usr", "/bin", "/sbin", "/lib",
                            "/lib64", "/boot", "/var", "/opt", "/srv", "/mnt", "/media")}
KOKLER |= {HOME, HOME / "Documents", HOME / "Desktop", HOME / "Downloads", PROJECTS, VAULT,
           HOME / ".local", HOME / ".local/share",
           HOME / ".local/state", HOME / ".config", HOME / ".claude", HOME / ".codex",
           HOME / ".ssh", HOME / ".gnupg"}
# İçinde toplu silme yapılmayan ağaçlar.
AGACLAR = (VAULT,)
ONBELLEK = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules",
            ".cache", "dist", "build", ".venv", "venv"}

ONEKLER = {"sudo", "doas", "command", "builtin", "exec", "nohup", "setsid", "time", "nice",
           "ionice", "stdbuf", "env", "timeout", "xargs", "then", "do", "else", "!"}
# Önek komutlarının değer alan bayrakları: `sudo -u x`, `xargs -I {}`, `timeout -k 2`.
DEGERLI_BAYRAK = {"-u", "-g", "-U", "-C", "-p", "-I", "-L", "-P", "-d", "-E", "-s", "-k", "-n",
                  "--signal", "--kill-after", "--user", "--group"}
KABUKLAR = {"sh", "bash", "zsh", "dash"}
AYIRICI = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;"}
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
YONLENDIRME = re.compile(r"\d*(?:>>?|<|&>>?)(.*)")
DEGISKEN = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
JOKER = re.compile(r"[*?\[]")


class Red(Exception):
    pass


def _heredoc_ayikla(metin: str) -> str:
    """Heredoc gövdeleri komut değil veridir; tırnak işaretleri shlex'i de bozar."""
    cikti, bekleyen = [], []
    for satir in metin.replace("\\\n", " ").splitlines():
        if bekleyen:
            if satir.strip() == bekleyen[0]:
                bekleyen.pop(0)
            continue
        cikti.append(satir)
        bekleyen = [m.group(2) for m in HEREDOC.finditer(satir)]
    return "\n".join(cikti)


def _jetonlar(satir: str) -> list[str]:
    try:
        # `&` noktalama sayılmaz: `2>&1` tek jeton kalsın; `&&` ve `&` boşlukla gelir.
        lex = shlex.shlex(satir, posix=True, punctuation_chars=";|()")
        lex.whitespace_split = True
        lex.commenters = "#"
        return list(lex)
    except ValueError:
        return satir.split()


def _komutlar(jetonlar: list[str]):
    parca: list[str] = []
    for j in jetonlar:
        if j in AYIRICI or (j and set(j) <= set(";&|()")):
            if parca:
                yield parca
            parca = []
        else:
            parca.append(j)
    if parca:
        yield parca


class Bekci:
    def __init__(self, cwd: str | None):
        self.cwd = Path(cwd) if cwd else Path.cwd()
        self.degiskenler = {"HOME": str(HOME), "CLAUDE_PROJECT_DIR": str(VAULT)}

    # --- yol --------------------------------------------------------------
    def _genislet(self, ham: str) -> str | None:
        if ham == "~" or ham.startswith("~/"):
            ham = str(HOME) + ham[1:]
        bilinmeyen = False

        def degis(m):
            nonlocal bilinmeyen
            ad = m.group(1) or m.group(2)
            if ad == "PWD":
                return str(self.cwd)
            if ad in self.degiskenler:
                return self.degiskenler[ad]
            if ad in os.environ:
                return os.environ[ad]
            bilinmeyen = True
            return ""

        sonuc = DEGISKEN.sub(degis, ham)
        # Boş kalan değişken `"$X"/` kalıbını `/` yapar: mutlak sonuç yine denetlenir.
        return None if bilinmeyen and not sonuc.startswith("/") else sonuc

    def _yol(self, ham: str) -> Path | None:
        genis = self._genislet(ham)
        if genis is None or not genis:
            return None
        return Path(os.path.normpath(self.cwd / genis))

    @staticmethod
    def _icinde(yol: Path, kok: Path) -> bool:
        return yol == kok or kok in yol.parents

    def _serbest(self, yol: Path) -> bool:
        return any(self._icinde(yol, s) for s in SERBEST)

    def _hedef_denetle(self, ham: str, ozyinelemeli: bool, arac: str) -> None:
        genis = self._genislet(ham)
        if not genis:
            return
        joker = bool(JOKER.search(genis))
        taban = genis
        if joker:
            # Jokerin bulunduğu bileşenden önceki klasör silinen içeriğin sahibidir.
            taban = (genis[: JOKER.search(genis).start()].rpartition("/")[0]
                     or ("/" if genis.startswith("/") else "."))
        yol = Path(os.path.normpath(self.cwd / taban))
        adaylar = {yol}
        try:
            adaylar.add(Path(os.path.realpath(yol)))
        except OSError:
            pass
        for aday in adaylar:
            if self._serbest(aday):
                continue
            if ONBELLEK & set(aday.parts) or (joker and ONBELLEK & set(Path(genis).parts)):
                continue
            if ozyinelemeli or joker:
                for kok in KOKLER:
                    if aday == kok or self._icinde(kok, aday):
                        raise Red(f"{arac} korunan kökü siliyor: {kok}")
                if aday.name == ".git":
                    raise Red(f"{arac} bir git geçmişini siliyor: {aday}")
                if aday.parent == PROJECTS:
                    raise Red(f"{arac} bir projenin tamamını siliyor: {aday}")
                for agac in AGACLAR:
                    if self._icinde(aday, agac):
                        raise Red(f"{arac} korunan ağaçta toplu silme yapıyor: {aday}")

    # --- komutlar ---------------------------------------------------------
    def denetle(self, metin: str, derinlik: int = 0) -> None:
        if derinlik > 3:
            return
        for satir in _heredoc_ayikla(metin).splitlines():
            for komut in _komutlar(_jetonlar(satir)):
                self._komut(komut, derinlik)

    def _komut(self, komut: list[str], derinlik: int) -> None:
        # Önek ve satır başı atamalarını soy: `sudo env X=1 timeout 5 rm ...`
        while komut:
            bas = komut[0].lstrip("\\")
            if re.fullmatch(r"[A-Za-z_]\w*=.*", bas):
                ad, _, deger = bas.partition("=")
                genis = self._genislet(deger)
                if genis is not None:
                    self.degiskenler[ad] = genis
                komut = komut[1:]
            elif bas == "export" and len(komut) > 1:
                komut = komut[1:]
            elif os.path.basename(bas) in ONEKLER:
                komut = komut[1:]
                while komut and (komut[0].startswith("-") or komut[0] == "{}"
                                 or re.fullmatch(r"[\d.]+[smhd]?", komut[0])):
                    komut = komut[2:] if komut[0] in DEGERLI_BAYRAK else komut[1:]
            else:
                break
        # Yönlendirmeler hedef değildir: `2>&1`, `> log`, `>/dev/null`.
        temiz: list[str] = []
        atla = False
        for jeton in komut:
            if atla:
                atla = False
                continue
            yon = YONLENDIRME.fullmatch(jeton)
            if yon and temiz:
                atla = not yon.group(1)
                continue
            temiz.append(jeton)
        komut = temiz
        if not komut:
            return
        ad, argumanlar = os.path.basename(komut[0].lstrip("\\")), komut[1:]
        if ad == "cd":
            hedef = self._yol(argumanlar[0] if argumanlar else "~")
            if hedef is not None:
                self.cwd = hedef
        elif ad == "eval":
            self.denetle(" ".join(argumanlar), derinlik + 1)
        elif ad in KABUKLAR:
            for i, a in enumerate(argumanlar[:-1]):
                if re.fullmatch(r"-[a-z]*c[a-z]*", a):
                    self.denetle(argumanlar[i + 1], derinlik + 1)
                    break
        elif ad == "rm":
            self._rm(ad, argumanlar)
        elif ad == "find":
            self._find(argumanlar)
        elif ad == "git":
            self._git(argumanlar)
        elif ad.startswith("mkfs") or ad in ("wipefs", "shred"):
            raise Red(f"{ad} veriyi kalıcı olarak yok ediyor")
        elif ad == "dd" and any(a.startswith("of=/dev/") and a not in ("of=/dev/null",) for a in argumanlar):
            raise Red("dd bir aygıtın üzerine yazıyor")

    def _rm(self, ad: str, argumanlar: list[str]) -> None:
        ozyinelemeli, hedefler, secenek_bitti = False, [], False
        for a in argumanlar:
            if not secenek_bitti and a == "--":
                secenek_bitti = True
            elif not secenek_bitti and a.startswith("--"):
                ozyinelemeli |= a == "--recursive"
            elif not secenek_bitti and a.startswith("-") and len(a) > 1:
                ozyinelemeli |= bool(set(a[1:]) & {"r", "R"})
            else:
                hedefler.append(a)
        if not hedefler and ozyinelemeli:
            # `... | xargs rm -rf`: hedef stdin'den gelir; korunan ağaçta körlemesine silme.
            for agac in AGACLAR:
                if self._icinde(self.cwd, agac):
                    raise Red(f"{ad} hedefi görünmeyen toplu silme, çalışma dizini {self.cwd}")
        for hedef in hedefler:
            self._hedef_denetle(hedef, ozyinelemeli, ad)

    def _find(self, argumanlar: list[str]) -> None:
        siliyor = "-delete" in argumanlar or any(
            a in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(argumanlar)
            and os.path.basename(argumanlar[i + 1]) in ("rm", "shred")
            for i, a in enumerate(argumanlar))
        if not siliyor or ONBELLEK & set(argumanlar):
            return
        baslangic = []
        for a in argumanlar:
            if a.startswith("-") or a in ("(", "!"):
                break
            baslangic.append(a)
        for yol in baslangic or ["."]:
            self._hedef_denetle(yol, True, "find")

    def _git(self, argumanlar: list[str]) -> None:
        cwd = self.cwd
        while argumanlar and argumanlar[0].startswith("-"):
            if argumanlar[0] in ("-C", "-c", "--git-dir", "--work-tree") and len(argumanlar) > 1:
                if argumanlar[0] == "-C":
                    cwd = self._yol(argumanlar[1]) or cwd
                argumanlar = argumanlar[2:]
            else:
                argumanlar = argumanlar[1:]
        if not argumanlar or self._serbest(cwd):
            return
        alt, geri = argumanlar[0], argumanlar[1:]
        bayraklar = {a for a in geri if a.startswith("-")}
        kisa = "".join(a[1:] for a in bayraklar if not a.startswith("--"))
        tum_agac = {".", ":/", "*", ":(top)"} & set(geri)
        if alt == "reset" and "--hard" in bayraklar:
            raise Red("git reset --hard kaydedilmemiş işi siler")
        if alt == "clean" and ("f" in kisa or "--force" in bayraklar) and not ("n" in kisa or "--dry-run" in bayraklar):
            raise Red("git clean -f izlenmeyen dosyaları siler")
        if alt == "checkout" and (tum_agac or "f" in kisa or "--force" in bayraklar):
            raise Red("git checkout çalışma ağacındaki değişiklikleri siler")
        if alt == "restore" and tum_agac and ("--worktree" in bayraklar or not {"--staged", "-S"} & bayraklar):
            raise Red("git restore çalışma ağacındaki değişiklikleri siler")
        if alt == "push" and ({"--force", "--force-with-lease", "--mirror", "--delete", "--prune"} & bayraklar
                              or any(b.startswith("--force") for b in bayraklar)
                              or "f" in kisa or "d" in kisa
                              or any(a.startswith("+") or (a.startswith(":") and len(a) > 1) for a in geri)):
            raise Red("git push uzak geçmişi siliyor ya da üzerine yazıyor (yedek deposu dahil)")
        if alt == "stash" and geri[:1] == ["clear"]:
            raise Red("git stash clear tüm saklananları siler")


def karar(girdi: dict) -> str | None:
    """Red nedeni ya da None. Testler doğrudan bunu çağırır."""
    if girdi.get("tool_name") != "Bash":
        return None
    komut = (girdi.get("tool_input") or {}).get("command")
    if not isinstance(komut, str) or not komut.strip():
        return None
    try:
        Bekci(girdi.get("cwd")).denetle(komut)
    except Red as red:
        return str(red)
    return None


def _kaydet(kayit: dict) -> None:
    try:
        yol = Path(os.environ.get("BEYIN_YIKICI_KAYIT") or STATE / "yikici-komut.jsonl")
        yol.parent.mkdir(parents=True, exist_ok=True)
        with yol.open("a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
        os.chmod(yol, 0o600)
    except OSError:
        pass


def main() -> int:
    try:
        girdi = json.load(sys.stdin)
        neden = karar(girdi)
    except Exception as exc:  # Bekçi hatası Bash'i kilitlememeli; iz kalsın.
        _kaydet({"ts": int(time.time()), "karar": "hata", "hata": type(exc).__name__})
        return 0
    if neden is None:
        return 0
    komut = str((girdi.get("tool_input") or {}).get("command", ""))
    _kaydet({"ts": int(time.time()), "karar": "red", "neden": neden, "komut": komut[:300],
             "oturum": girdi.get("session_id")})
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Beyin yıkıcı komut bekçisi durdurdu: {neden}. Bu işlem geri alınamaz. Kullanıcıya neyi "
            "neden sileceğini söyle ve onay iste; onaylarsa komutu kendisi `! <komut>` ile "
            "çalıştırır. Kancayı atlatmaya çalışma."),
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
