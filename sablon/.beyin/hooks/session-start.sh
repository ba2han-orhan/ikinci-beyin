#!/bin/bash
[ -n "${BEYIN_INVOKED_BY:-}" ] && exit 0
# Inject relational memory, rules, recent journal context, and the knowledge index.

BEYIN_HOOK_DIR=$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd)
. "$BEYIN_HOOK_DIR/lib.sh" 2>/dev/null || exit 0

BEYIN_MEMORY_DIR="$BEYIN_PROJECT_DIR/850-hafiza"
BEYIN_NL='
'

# Claude Code her hook çıktısını 10.000 karakterle sınırlar; bu yüzden settings.json
# bu script'i iki kez çalıştırır: "kurallar" yalnız kuralları, "hafiza" geri kalanı basar.
BEYIN_PART=${1:-hepsi}
BEYIN_METRIC_ID="$(date +%s)-$$-$BEYIN_PART"
beyin_context_metric() {
  [ -f "$BEYIN_PROJECT_DIR/.beyin/scripts/context_metrics.py" ] || return 0
  python3 "$BEYIN_PROJECT_DIR/.beyin/scripts/context_metrics.py" --state "$BEYIN_STATE_DIR" \
    --id "$BEYIN_METRIC_ID" "$@" >/dev/null 2>&1 || :
}
beyin_context_metric --event started

BEYIN_RULES=""
BEYIN_RULES_PATH="$BEYIN_MEMORY_DIR/davranis-kurallari.md"
[ -f "$BEYIN_MEMORY_DIR/calisma-cekirdegi.md" ] && BEYIN_RULES_PATH="$BEYIN_MEMORY_DIR/calisma-cekirdegi.md"
if [ "$BEYIN_PART" != hafiza ] && [ -f "$BEYIN_RULES_PATH" ]; then
  BEYIN_RULES=$(awk '
    /^## Nasıl büyür/ { exit }
    /^## Kurallar/ { active = 1 }
    active { print }
  ' "$BEYIN_RULES_PATH" 2>/dev/null)
fi

if [ "$BEYIN_PART" = kurallar ]; then
  # No state, no compile: the "hafiza" run does those once.
  BEYIN_RULES_NOTE='[not: kurallar 9.900 karakterde kırpıldı, beyin-doktor çalıştır]'
  BEYIN_RULES_RAW=${#BEYIN_RULES}
  BEYIN_RULES_TRIMMED=""
  if [ "${#BEYIN_RULES}" -gt 9900 ]; then
    BEYIN_RULES_TRIMMED="--trimmed"
    BEYIN_RULES="${BEYIN_RULES:0:$((9899 - ${#BEYIN_RULES_NOTE}))}${BEYIN_NL}${BEYIN_RULES_NOTE}"
  fi
  BEYIN_RULES_OUTPUT=""
  if [ -n "$BEYIN_RULES" ]; then
    BEYIN_RULES_OUTPUT="[Hafıza: Kurallar]${BEYIN_NL}${BEYIN_RULES}"
    beyin_emit SessionStart "$BEYIN_RULES_OUTPUT"
  fi
  beyin_context_metric --event delivered --chars "${#BEYIN_RULES_OUTPUT}" $BEYIN_RULES_TRIMMED \
    --part kurallar --rules-source "${BEYIN_RULES_PATH##*/}" \
    --section rules "$BEYIN_RULES_RAW" "${#BEYIN_RULES}" "${#BEYIN_RULES}" 9900 0
  exit 0
fi

mkdir -p "$BEYIN_STATE_DIR" 2>/dev/null || :
beyin_cleanup_session_state

BEYIN_HOOK_INPUT=$(cat)
BEYIN_SESSION_KEY=$(printf '%s' "$BEYIN_HOOK_INPUT" | beyin_session_key 2>/dev/null || :)
if [ -n "$BEYIN_SESSION_KEY" ]; then
  BEYIN_SESSION_START_FILE="$BEYIN_STATE_DIR/session_start_time.$BEYIN_SESSION_KEY"
  BEYIN_PROMPT_COUNT_FILE="$BEYIN_STATE_DIR/prompt_count.$BEYIN_SESSION_KEY"
  [ -f "$BEYIN_SESSION_START_FILE" ] || date '+%s' > "$BEYIN_SESSION_START_FILE" 2>/dev/null || :
  [ -f "$BEYIN_PROMPT_COUNT_FILE" ] || printf '%s\n' 0 > "$BEYIN_PROMPT_COUNT_FILE" 2>/dev/null || :
fi

# Only the newest session in full; the next five by title. The rest of the
# file is one Read away, and the daily log below repeats these same sessions.
BEYIN_LAST_SESSION=""
if [ -f "$BEYIN_MEMORY_DIR/son-oturum-ozetleri.md" ]; then
  BEYIN_LAST_SESSION=$(awk '
    /^## Previous/ { exit }
    /^## Session:/ {
      n++
      if (n > 1) { if (n <= 6) titles = titles "- " substr($0, 13) "\n"; next }
    }
    n == 1 { print }
    END {
      if (titles != "") printf "\nÖnceki oturumlar (tamamı 850-hafiza/son-oturum-ozetleri.md):\n%s", titles
    }
  ' "$BEYIN_MEMORY_DIR/son-oturum-ozetleri.md" 2>/dev/null | sed -n '1,60p')
fi

BEYIN_THREADS=""
BEYIN_THREADS_TOTAL=0
BEYIN_THREADS_OMITTED=0
BEYIN_THREADS_MODE=priority
BEYIN_THREADS_FILE="$BEYIN_MEMORY_DIR/aktif-konu-takibi.md"
BEYIN_THREADS_SELECTOR="$BEYIN_PROJECT_DIR/.beyin/scripts/select_threads.py"
if [ -f "$BEYIN_THREADS_FILE" ]; then
  if [ -f "$BEYIN_THREADS_SELECTOR" ] && BEYIN_THREADS_SELECTION=$(printf '%s' "$BEYIN_HOOK_INPUT" | python3 "$BEYIN_THREADS_SELECTOR" --source "$BEYIN_THREADS_FILE" --cwd "$PWD" --payload --format hook 2>/dev/null); then
    read -r BEYIN_THREADS_TOTAL BEYIN_THREADS_OMITTED BEYIN_THREADS_MODE <<< "${BEYIN_THREADS_SELECTION%%$BEYIN_NL*}"
    case "$BEYIN_THREADS_SELECTION" in
      *"$BEYIN_NL"*) BEYIN_THREADS=${BEYIN_THREADS_SELECTION#*$BEYIN_NL} ;;
    esac
  else
    # Missing/broken selector: provide a complete source pointer, never legacy cuts.
    BEYIN_THREADS_TOTAL=$(sed -n '/^## Active/,/^## Closed/p' "$BEYIN_THREADS_FILE" | awk '/^### / { n++ } END { print n+0 }')
    BEYIN_THREADS_OMITTED=$BEYIN_THREADS_TOTAL
    BEYIN_THREADS_MODE=unavailable
    BEYIN_THREADS='Aktif konu seçicisi çalışmadı. [[aktif-konu-takibi|Konuları kaynaktan oku]].'
  fi
fi

BEYIN_JOURNAL=""
if [ -f "$BEYIN_MEMORY_DIR/gunluk-gozlemleri.md" ]; then
  BEYIN_JOURNAL=$(awk '
    /^## / {
      active=0
      if ($2 ~ /^[0-9][0-9]\.[0-9][0-9]\.[0-9][0-9][0-9][0-9]$/) {
        split($2,d,"."); stamp=d[3] d[2] d[1]
        if (stamp > latest) { latest=stamp; text=$0; count=1; active=1 }
      }
      next
    }
    active && count < 10 { text=text "\n" $0; count++ }
    END { if (text != "") print text }
  ' "$BEYIN_MEMORY_DIR/gunluk-gozlemleri.md" 2>/dev/null)
fi

# The index is read on demand; avoid injecting every historical topic.
BEYIN_INDEX=""
BEYIN_INDEX_FILE="$BEYIN_PROJECT_DIR/550-derlenmis-bilgi-tabani/bilgi-tabani-indeksi.md"
if [ -f "$BEYIN_INDEX_FILE" ]; then
  BEYIN_INDEX_COUNT=$(awk '/^\| \[\[/ { n++ } END { print n+0 }' "$BEYIN_INDEX_FILE")
  BEYIN_INDEX="${BEYIN_INDEX_COUNT} makale. Görevle ilgili bilgiyi 550-derlenmis-bilgi-tabani/bilgi-tabani-indeksi.md içinde ara; yalnız eşleşen concepts/ notlarını oku."
fi

BEYIN_DAILY=""
BEYIN_TODAY=$(date '+%d.%m.%Y' 2>/dev/null || :)
BEYIN_DAILY_FILE=""
if [ -n "$BEYIN_TODAY" ] && [ -f "$BEYIN_PROJECT_DIR/800-gunluk-oturum-kayitlari/$BEYIN_TODAY.md" ]; then
  BEYIN_DAILY_FILE="$BEYIN_PROJECT_DIR/800-gunluk-oturum-kayitlari/$BEYIN_TODAY.md"
else
  BEYIN_YESTERDAY=$(beyin_yesterday)
  if [ -n "$BEYIN_YESTERDAY" ] && [ -f "$BEYIN_PROJECT_DIR/800-gunluk-oturum-kayitlari/$BEYIN_YESTERDAY.md" ]; then
    BEYIN_DAILY_FILE="$BEYIN_PROJECT_DIR/800-gunluk-oturum-kayitlari/$BEYIN_YESTERDAY.md"
  fi
fi
# A pointer, not the text: the machine summaries repeat the sessions above.
if [ -n "$BEYIN_DAILY_FILE" ]; then
  BEYIN_DAILY_COUNT=$(grep -c '^### Oturum' "$BEYIN_DAILY_FILE" 2>/dev/null)
  BEYIN_DAILY_LAST=$(grep '^### Oturum' "$BEYIN_DAILY_FILE" 2>/dev/null | tail -n 1 | sed 's/^### //')
  BEYIN_DAILY="800-gunluk-oturum-kayitlari/${BEYIN_DAILY_FILE##*/}: ${BEYIN_DAILY_COUNT:-0} oturum kaydı${BEYIN_DAILY_LAST:+, sonuncusu ${BEYIN_DAILY_LAST}}. Gerekirse oku."
fi

# Hata defteri: hata_defteri.py analizinin tek satırı; bekleyen yoksa dosya boştur.
BEYIN_ERRORS=""
BEYIN_ERRORS_FILE="$BEYIN_PROJECT_DIR/.beyin/scripts/.state/hata-defteri-ozet.txt"
if [ -f "$BEYIN_ERRORS_FILE" ]; then
  BEYIN_ERRORS=$(sed -n '1p' "$BEYIN_ERRORS_FILE" 2>/dev/null | cut -c1-400)
fi

# Sağlık: yedek.sh başarısız olursa yazar; sorun yoksa dosya yoktur.
BEYIN_HEALTH=""
BEYIN_HEALTH_FILE="$BEYIN_PROJECT_DIR/.beyin/scripts/.state/saglik-uyari.txt"
if [ -f "$BEYIN_HEALTH_FILE" ]; then
  BEYIN_HEALTH=$(sed -n '1p' "$BEYIN_HEALTH_FILE" 2>/dev/null | cut -c1-400)
fi

BEYIN_REFLECTION=""
for BEYIN_REFLECTION_FILE in \
  "$BEYIN_STATE_DIR/needs_reflection" \
  "$BEYIN_STATE_DIR"/needs_reflection.*
do
  [ -f "$BEYIN_REFLECTION_FILE" ] || continue
  BEYIN_REFLECTION_DETAIL=$(sed -n '1p' "$BEYIN_REFLECTION_FILE" 2>/dev/null || :)
  if [ -n "$BEYIN_REFLECTION_DETAIL" ]; then
    [ -n "$BEYIN_REFLECTION" ] && BEYIN_REFLECTION="${BEYIN_REFLECTION}${BEYIN_NL}"
    BEYIN_REFLECTION="${BEYIN_REFLECTION}⚠️ Önceki oturum hafıza güncellemeden bitti: ${BEYIN_REFLECTION_DETAIL}. Anlamlı bir şey olduysa 850-hafiza dosyalarını güncelle."
  fi
  rm -f "$BEYIN_REFLECTION_FILE" 2>/dev/null || :
done

# Hard section entry caps, including truncation notes: Last Session 4500,
# Threads 2000, Kurallar 10000, Journal 1500, reflection debt 1000 characters.
# The budget below holds every section whole (27.09: ~15k with the rules,
# ~6k without, the "hafiza" part must stay under Claude's 10,000). It is
# deliberately not tight: a budget that always trims prints a
# "beyin-doktor çalıştır" note every single session, which trains the reader to
# ignore a warning that is supposed to mean something.
# Kurallar is extracted by section (## Kurallar to ## Nasıl büyür), not by
# line count, so this cap is the only thing bounding it as rules accumulate.
beyin_cap_section() {
  BEYIN_CAP_VALUE=$1
  BEYIN_CAP_LIMIT=$2
  BEYIN_CAP_NOTE=$3
  if [ "${#BEYIN_CAP_VALUE}" -le "$BEYIN_CAP_LIMIT" ]; then
    printf '%s' "$BEYIN_CAP_VALUE"
    return 0
  fi

  BEYIN_CAP_KEEP=$((BEYIN_CAP_LIMIT - ${#BEYIN_CAP_NOTE} - 1))
  [ "$BEYIN_CAP_KEEP" -gt 0 ] || BEYIN_CAP_KEEP=0
  printf '%s\n%s' "${BEYIN_CAP_VALUE:0:$BEYIN_CAP_KEEP}" "$BEYIN_CAP_NOTE"
}

BEYIN_LAST_SESSION_RAW=${#BEYIN_LAST_SESSION}
BEYIN_THREADS_RAW=${#BEYIN_THREADS}
BEYIN_RULES_RAW=${#BEYIN_RULES}
BEYIN_JOURNAL_RAW=${#BEYIN_JOURNAL}
BEYIN_REFLECTION_RAW=${#BEYIN_REFLECTION}
BEYIN_INDEX_RAW=${#BEYIN_INDEX}
BEYIN_DAILY_RAW=${#BEYIN_DAILY}
BEYIN_ERRORS_RAW=${#BEYIN_ERRORS}

BEYIN_LAST_SESSION=$(beyin_cap_section "$BEYIN_LAST_SESSION" 4500 \
  '[not: son oturum 4.500 karakterde kırpıldı, beyin-doktor çalıştır]')
BEYIN_THREADS=$(beyin_cap_section "$BEYIN_THREADS" 2000 \
  '[not: aktif konular 2.000 karakterde kırpıldı, beyin-doktor çalıştır]')
BEYIN_RULES=$(beyin_cap_section "$BEYIN_RULES" 10000 \
  '[not: kurallar 10.000 karakterde kırpıldı, beyin-doktor çalıştır]')
BEYIN_JOURNAL=$(beyin_cap_section "$BEYIN_JOURNAL" 1500 \
  '[not: son Journal 1.500 karakterde kırpıldı, beyin-doktor çalıştır]')
BEYIN_REFLECTION=$(beyin_cap_section "$BEYIN_REFLECTION" 1000 \
  '[not: hafıza uyarıları 1.000 karakterde kırpıldı, beyin-doktor çalıştır]')

BEYIN_LAST_SESSION_CAPPED=${#BEYIN_LAST_SESSION}
BEYIN_THREADS_CAPPED=${#BEYIN_THREADS}
BEYIN_RULES_CAPPED=${#BEYIN_RULES}
BEYIN_JOURNAL_CAPPED=${#BEYIN_JOURNAL}
BEYIN_REFLECTION_CAPPED=${#BEYIN_REFLECTION}
BEYIN_INDEX_CAPPED=${#BEYIN_INDEX}
BEYIN_DAILY_CAPPED=${#BEYIN_DAILY}
BEYIN_ERRORS_CAPPED=${#BEYIN_ERRORS}

BEYIN_TRUNCATED=0
BEYIN_CLOSING='[Hafıza] Süreklilik senin sorumluluğun. Bu kullanıcı için kim olduğunu anlamak üzere 850-hafiza/kimlik-cekirdegi.md dosyasını oku.
Hafıza protokolü zorunludur.'
BEYIN_TRUNCATION_NOTE='[not: indeks kırpıldı, beyin-doktor çalıştır]'
BEYIN_BUDGET=23000
[ "$BEYIN_PART" = hafiza ] && BEYIN_BUDGET=9900
BEYIN_CAP_DIAGNOSTIC="Beyin uyarısı: Oturum başlangıç bağlamı $BEYIN_BUDGET karakter sınırına sığmadı. Bölüm limitlerini kontrol etmek için beyin-doktor çalıştır."

beyin_build_context() {
  BEYIN_CONTEXT=""
  [ -n "$BEYIN_HEALTH" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Sağlık] ⚠️ ${BEYIN_HEALTH} kullanıcıya ilk yanıtta söyle.${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_REFLECTION" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}${BEYIN_REFLECTION}${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_LAST_SESSION" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Hafıza: Son Oturum]${BEYIN_NL}${BEYIN_LAST_SESSION}${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_THREADS" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Hafıza: Aktif Konular]${BEYIN_NL}${BEYIN_THREADS}${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_RULES" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Hafıza: Kurallar]${BEYIN_NL}${BEYIN_RULES}${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_JOURNAL" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Hafıza: Son Journal]${BEYIN_NL}${BEYIN_JOURNAL}${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_INDEX" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Bilgi Tabanı: İndeks]${BEYIN_NL}${BEYIN_INDEX}${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_DAILY" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Bugünün Logu]${BEYIN_NL}${BEYIN_DAILY}${BEYIN_NL}${BEYIN_NL}"
  [ -n "$BEYIN_ERRORS" ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}[Hata Defteri]${BEYIN_NL}${BEYIN_ERRORS}${BEYIN_NL}${BEYIN_NL}"
  [ "$BEYIN_TRUNCATED" -eq 1 ] && BEYIN_CONTEXT="${BEYIN_CONTEXT}${BEYIN_TRUNCATION_NOTE}${BEYIN_NL}${BEYIN_NL}"
  BEYIN_CONTEXT="${BEYIN_CONTEXT}${BEYIN_CLOSING}"
}

beyin_build_context
if [ "${#BEYIN_CONTEXT}" -gt "$BEYIN_BUDGET" ]; then
  BEYIN_TRUNCATED=1
  beyin_build_context

  BEYIN_OVER=$(( ${#BEYIN_CONTEXT} - BEYIN_BUDGET ))
  if [ "$BEYIN_OVER" -gt 0 ] && [ -n "$BEYIN_INDEX" ]; then
    if [ "$BEYIN_OVER" -ge "${#BEYIN_INDEX}" ]; then
      BEYIN_INDEX=""
    else
      BEYIN_KEEP=$(( ${#BEYIN_INDEX} - BEYIN_OVER ))
      BEYIN_INDEX=${BEYIN_INDEX:0:$BEYIN_KEEP}
    fi
    beyin_build_context
  fi

  BEYIN_OVER=$(( ${#BEYIN_CONTEXT} - BEYIN_BUDGET ))
  if [ "$BEYIN_OVER" -gt 0 ] && [ -n "$BEYIN_DAILY" ]; then
    if [ "$BEYIN_OVER" -ge "${#BEYIN_DAILY}" ]; then
      BEYIN_DAILY=""
    else
      BEYIN_DAILY=${BEYIN_DAILY:$BEYIN_OVER}
    fi
    beyin_build_context
  fi

  # Journal and reflection are the only remaining non-protected sections.
  BEYIN_OVER=$(( ${#BEYIN_CONTEXT} - BEYIN_BUDGET ))
  if [ "$BEYIN_OVER" -gt 0 ] && [ -n "$BEYIN_JOURNAL" ]; then
    if [ "$BEYIN_OVER" -ge "${#BEYIN_JOURNAL}" ]; then
      BEYIN_JOURNAL=""
    else
      BEYIN_KEEP=$(( ${#BEYIN_JOURNAL} - BEYIN_OVER ))
      BEYIN_JOURNAL=${BEYIN_JOURNAL:0:$BEYIN_KEEP}
    fi
    beyin_build_context
  fi

  BEYIN_OVER=$(( ${#BEYIN_CONTEXT} - BEYIN_BUDGET ))
  if [ "$BEYIN_OVER" -gt 0 ] && [ -n "$BEYIN_REFLECTION" ]; then
    if [ "$BEYIN_OVER" -ge "${#BEYIN_REFLECTION}" ]; then
      BEYIN_REFLECTION=""
    else
      BEYIN_KEEP=$(( ${#BEYIN_REFLECTION} - BEYIN_OVER ))
      BEYIN_REFLECTION=${BEYIN_REFLECTION:0:$BEYIN_KEEP}
    fi
    beyin_build_context
  fi
fi

if [ "${#BEYIN_CONTEXT}" -gt "$BEYIN_BUDGET" ]; then
  BEYIN_CONTEXT=$BEYIN_CAP_DIAGNOSTIC
fi

[ -n "$BEYIN_CONTEXT" ] && beyin_emit SessionStart "$BEYIN_CONTEXT"
BEYIN_METRIC_FLAGS=()
[ "$BEYIN_TRUNCATED" = 1 ] && BEYIN_METRIC_FLAGS+=(--budget-trimmed)
if [ "$BEYIN_CONTEXT" = "$BEYIN_CAP_DIAGNOSTIC" ]; then
  BEYIN_METRIC_FLAGS+=(--budget-trimmed)
  BEYIN_LAST_SESSION=""
  BEYIN_THREADS=""
  BEYIN_RULES=""
  BEYIN_JOURNAL=""
  BEYIN_REFLECTION=""
  BEYIN_INDEX=""
  BEYIN_DAILY=""
  BEYIN_ERRORS=""
  BEYIN_THREADS_OMITTED=$BEYIN_THREADS_TOTAL
fi
beyin_context_metric --event delivered --chars "${#BEYIN_CONTEXT}" \
  --part "$BEYIN_PART" --rules-source "${BEYIN_RULES_PATH##*/}" --selection-mode "$BEYIN_THREADS_MODE" "${BEYIN_METRIC_FLAGS[@]}" \
  --section last_session "$BEYIN_LAST_SESSION_RAW" "$BEYIN_LAST_SESSION_CAPPED" "${#BEYIN_LAST_SESSION}" 4500 0 \
  --section threads "$BEYIN_THREADS_RAW" "$BEYIN_THREADS_CAPPED" "${#BEYIN_THREADS}" 2000 "$BEYIN_THREADS_OMITTED" \
  --section rules "$BEYIN_RULES_RAW" "$BEYIN_RULES_CAPPED" "${#BEYIN_RULES}" 10000 0 \
  --section journal "$BEYIN_JOURNAL_RAW" "$BEYIN_JOURNAL_CAPPED" "${#BEYIN_JOURNAL}" 1500 0 \
  --section reflection "$BEYIN_REFLECTION_RAW" "$BEYIN_REFLECTION_CAPPED" "${#BEYIN_REFLECTION}" 1000 0 \
  --section index "$BEYIN_INDEX_RAW" "$BEYIN_INDEX_CAPPED" "${#BEYIN_INDEX}" 0 0 \
  --section daily "$BEYIN_DAILY_RAW" "$BEYIN_DAILY_CAPPED" "${#BEYIN_DAILY}" 0 0 \
  --section errors "$BEYIN_ERRORS_RAW" "$BEYIN_ERRORS_CAPPED" "${#BEYIN_ERRORS}" 0 0

# The evening compile is triggered from SessionEnd, which means a day whose last
# session closes before 18:00 never reaches it and its log sits uncompiled. Fire
# the catch-up pass here, detached and after the context is already emitted so it
# can neither delay the session nor corrupt the hook's JSON on stdout. flush.py
# decides whether anything is actually due; the call is cheap when it is not.
if command -v python3 >/dev/null 2>&1; then
  beyin_detach python3 "$BEYIN_PROJECT_DIR/.beyin/scripts/flush.py" --maybe-compile
fi


exit 0
