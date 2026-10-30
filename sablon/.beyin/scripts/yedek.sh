#!/bin/bash
# Vault'u git ile yedekler: değişiklik varsa commit, remote varsa push.
# Zamanlayıcıdan (cron / systemd --user) ya da elle çalışır. Hata olursa
# .beyin/scripts/.state/saglik-uyari.txt yazar; session-start bunu ilk yanıtta gösterir.
set -u
VAULT=$(CDPATH= cd "$(dirname "$0")/../.." && pwd) || exit 1
UYARI="$VAULT/.beyin/scripts/.state/saglik-uyari.txt"
cd "$VAULT" || exit 1
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Yedek: vault bir git deposu değil." > "$UYARI"; exit 1; }

git add -A
if git diff --cached --name-only | grep -qE 'settings\.local\.json|\.yedek|\.bak$|(^|/)\.env$'; then
  git reset -q
  echo "Yedek durdu: sır taşıyabilecek dosya sahnelendi, .gitignore'u kontrol et." > "$UYARI"
  exit 1
fi
if ! git diff --cached --quiet; then
  ADET=$(git diff --cached --name-only | wc -l | tr -d ' ')
  git -c user.name="$(git config user.name || echo beyin)" -c user.email="$(git config user.email || echo beyin@localhost)" \
    commit -q -m "Otomatik yedek: $(date '+%d.%m.%Y %H:%M') — $ADET dosya" || { echo "Yedek: commit başarısız." > "$UYARI"; exit 1; }
fi
if git remote | grep -q .; then
  GIT_TERMINAL_PROMPT=0 git push -q 2>/dev/null || { echo "Yedek: push başarısız ($(date '+%d.%m.%Y %H:%M')). Ağ ya da kimlik bilgisini kontrol et." > "$UYARI"; exit 1; }
fi
rm -f "$UYARI"
exit 0
