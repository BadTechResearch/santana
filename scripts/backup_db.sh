#!/usr/bin/env bash
# backup_db.sh — Backup automatique des bases SQLite
# Utilise sqlite3 .backup (API online backup) = sûr même en écriture concurrente
# Usage: ./scripts/backup_db.sh              # backup complet
#        ./scripts/backup_db.sh --list       # lister les backups existants
#        ./scripts/backup_db.sh --clean      # nettoyer les backups > 7 jours

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

BACKUP_DIR="_backups"
RETENTION_DAYS=3
TIMESTAMP=$(date +%Y-%m-%dT%H%M%S)

# Bases de données à backup
DATABASES=(
    "memory.db:memory"
    "metrics.db:metrics"
)

# ── Alerte Telegram ──────────────────────────────────────────────────────────
# Sans ça, un integrity_check qui échoue ne produit qu'un echo perdu dans un
# cron silencieux (cause du délai de détection de la corruption du 19/06).
notify_telegram() {
    local MSG="$1"
    local TOKEN=$(grep -m1 "^TELEGRAM_TOKEN=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2-)
    local CHAT=$(grep -m1 "^CHAT_ID=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2-)
    if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
        echo "  ⚠️  Alerte Telegram impossible : TELEGRAM_TOKEN/CHAT_ID absents de .env"
        return
    fi
    curl -s -m 10 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        -d "chat_id=${CHAT}" --data-urlencode "text=${MSG}" > /dev/null
}

# ── Fonctions ────────────────────────────────────────────────────────────────

backup_db() {
    local DB_PATH="$1"
    local DB_NAME="$2"
    local BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.db"

    if [ ! -f "$DB_PATH" ]; then
        echo "⚠️  $DB_PATH n'existe pas, ignoré"
        return
    fi

    # Vérifier que le fichier est une base SQLite valide AVANT le backup —
    # alerte immédiate si échec (pas juste un echo dans un cron silencieux).
    if ! sqlite3 "$DB_PATH" "PRAGMA integrity_check" 2>/dev/null | grep -q "^ok$"; then
        echo "⚠️  $DB_PATH — INTEGRITY CHECK ÉCHOUÉ, backup quand même"
        notify_telegram "🚨 Santana : PRAGMA integrity_check a échoué sur ${DB_PATH} avant le backup du $(date '+%Y-%m-%d %H:%M'). Vérifier et restaurer depuis un backup propre si nécessaire."
    fi

    # Backup via SQLite online backup API (sûr même en écriture)
    if sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'" 2>/dev/null; then
        local SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        echo "  ✅ $DB_NAME → $BACKUP_FILE ($SIZE)"
    else
        echo "  ❌ Échec backup $DB_NAME"
        return 1
    fi
}

list_backups() {
    echo "=== Backups existants ==="
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo "  Aucun backup"
        return
    fi
    for db in memory metrics; do
        echo ""
        echo "  📁 $db :"
        ls -1tr "$BACKUP_DIR/${db}_"*.db 2>/dev/null | while read -r f; do
            local SIZE=$(du -h "$f" 2>/dev/null | cut -f1)
            local AGE=$(( ($(date +%s) - $(stat -c %Y "$f")) / 86400 ))
            echo "    $(basename "$f") — ${SIZE} — ${AGE}j"
        done
    done
    echo ""
    du -sh "$BACKUP_DIR" 2>/dev/null | awk '{print "  Total: " $1}'
}

clean_old_backups() {
    echo "=== Nettoyage des backups > ${RETENTION_DAYS} jours ==="
    local COUNT=0
    for f in "$BACKUP_DIR/"*.db; do
        [ -f "$f" ] || continue
        local AGE=$(( ($(date +%s) - $(stat -c %Y "$f")) / 86400 ))
        if [ "$AGE" -gt "$RETENTION_DAYS" ]; then
            rm -v "$f"
            COUNT=$((COUNT + 1))
        fi
    done
    if [ "$COUNT" -eq 0 ]; then
        echo "  Rien à nettoyer"
    else
        echo "  $COUNT backup(s) supprimé(s)"
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

case "${1:-}" in
    --list)
        list_backups
        exit 0
        ;;
    --clean)
        clean_old_backups
        exit 0
        ;;
    --help|-h)
        echo "Usage: $0 [--list|--clean|--help]"
        echo "  (sans argument)  → backup de toutes les bases"
        echo "  --list           → lister les backups existants"
        echo "  --clean          → supprimer les backups > ${RETENTION_DAYS}j"
        exit 0
        ;;
esac

mkdir -p "$BACKUP_DIR"

echo "📦 Backup SQLite — $(date)"
echo ""

for entry in "${DATABASES[@]}"; do
    DB_PATH="${entry%%:*}"
    DB_NAME="${entry##*:}"
    backup_db "$DB_PATH" "$DB_NAME"
done

echo ""
echo "✅ Backup terminé"

# Nettoyage automatique
clean_old_backups 2>/dev/null || true

echo ""
echo "📊 Espace utilisé : $(du -sh "$BACKUP_DIR" | cut -f1)"
