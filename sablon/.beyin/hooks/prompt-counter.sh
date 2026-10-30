#!/bin/bash
[ -n "${BEYIN_INVOKED_BY:-}" ] && exit 0
# Count prompts and nudge at every multiple of fifteen.

BEYIN_HOOK_DIR=$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd)
. "$BEYIN_HOOK_DIR/lib.sh" 2>/dev/null || exit 0

# Hook girdisi hem 000 yakalama hem oturum anahtarı için gerekiyor; stdin tek okunur.
BEYIN_HOOK_INPUT="$BEYIN_STATE_DIR/hookin-$$.json"
umask 077
if ! cat > "$BEYIN_HOOK_INPUT" 2>/dev/null; then
  rm -f "$BEYIN_HOOK_INPUT" 2>/dev/null || :
  exit 0
fi

# A standalone trailing 000 is an explicit request to capture this message.
# Keep this synchronous and before other consumers may remove the hook input.
BEYIN_CAPTURE_TEXT=""
BEYIN_CAPTURE_SCRIPT="$BEYIN_PROJECT_DIR/.beyin/scripts/capture-000.py"
if [ -f "$BEYIN_CAPTURE_SCRIPT" ] && command -v python3 >/dev/null 2>&1; then
  BEYIN_CAPTURE_RESULT=$(python3 "$BEYIN_CAPTURE_SCRIPT" \
    --hook-input "$BEYIN_HOOK_INPUT" --root "$BEYIN_PROJECT_DIR" 2>/dev/null || :)
  case "$BEYIN_CAPTURE_RESULT" in
    __CAPTURE_FAILED__)
      BEYIN_CAPTURE_TEXT="000 yakalama başarısız oldu; not dosyasına kaydedilmedi."
      ;;
    '') ;;
    *) BEYIN_CAPTURE_TEXT=$BEYIN_CAPTURE_RESULT ;;
  esac
else
  BEYIN_CAPTURE_TEXT="000 yakalama bileşeni kullanılamadı; not kaydı doğrulanamadı."
fi

BEYIN_SESSION_KEY=$(beyin_session_key < "$BEYIN_HOOK_INPUT" 2>/dev/null || :)
if [ -z "$BEYIN_SESSION_KEY" ]; then
  [ -n "$BEYIN_CAPTURE_TEXT" ] && beyin_emit UserPromptSubmit "$BEYIN_CAPTURE_TEXT"
  rm -f "$BEYIN_HOOK_INPUT" 2>/dev/null || :
  exit 0
fi

BEYIN_PROMPT_COUNT_FILE="$BEYIN_STATE_DIR/prompt_count.$BEYIN_SESSION_KEY"
BEYIN_LOCK_DIR="$BEYIN_PROMPT_COUNT_FILE.lock"
BEYIN_LOCK_ATTEMPT=0
while ! mkdir "$BEYIN_LOCK_DIR" 2>/dev/null; do
  BEYIN_LOCK_ATTEMPT=$((BEYIN_LOCK_ATTEMPT + 1))
  if [ "$BEYIN_LOCK_ATTEMPT" -ge 500 ]; then
    rm -f "$BEYIN_HOOK_INPUT" 2>/dev/null || :
    exit 0
  fi
  sleep 0.01 2>/dev/null || sleep 1 2>/dev/null || exit 0
done
trap 'rmdir "$BEYIN_LOCK_DIR" 2>/dev/null || :; rm -f "$BEYIN_HOOK_INPUT" 2>/dev/null || :' EXIT
trap 'exit 0' HUP INT TERM

BEYIN_COUNT=0
if [ -f "$BEYIN_PROMPT_COUNT_FILE" ]; then
  BEYIN_COUNT=$(sed -n '1p' "$BEYIN_PROMPT_COUNT_FILE" 2>/dev/null || :)
fi
case "$BEYIN_COUNT" in
  ''|*[!0-9]*) BEYIN_COUNT=0 ;;
esac

BEYIN_COUNT=$((BEYIN_COUNT + 1))
BEYIN_COUNT_TMP="$BEYIN_PROMPT_COUNT_FILE.tmp.$$"
if printf '%s\n' "$BEYIN_COUNT" > "$BEYIN_COUNT_TMP" 2>/dev/null; then
  mv -f "$BEYIN_COUNT_TMP" "$BEYIN_PROMPT_COUNT_FILE" 2>/dev/null || :
fi
rm -f "$BEYIN_COUNT_TMP" 2>/dev/null || :
rmdir "$BEYIN_LOCK_DIR" 2>/dev/null || :
trap - EXIT HUP INT TERM

rm -f "$BEYIN_HOOK_INPUT" 2>/dev/null || :

BEYIN_NUDGE=""
if [ $((BEYIN_COUNT % 15)) -eq 0 ]; then
  BEYIN_NUDGE="[Hafıza] $BEYIN_COUNT. mesaj. Oturum sonunda 850-hafiza/son-oturum-ozetleri.md ve aktif-konu-takibi.md güncellemeyi unutma."
fi
BEYIN_HOOK_CONTEXT="$BEYIN_NUDGE"
if [ -n "$BEYIN_CAPTURE_TEXT" ]; then
  [ -n "$BEYIN_HOOK_CONTEXT" ] && BEYIN_HOOK_CONTEXT="$BEYIN_HOOK_CONTEXT

"
  BEYIN_HOOK_CONTEXT="$BEYIN_HOOK_CONTEXT$BEYIN_CAPTURE_TEXT"
fi
if [ -n "$BEYIN_HOOK_CONTEXT" ]; then
  beyin_emit UserPromptSubmit "$BEYIN_HOOK_CONTEXT"
fi
exit 0
