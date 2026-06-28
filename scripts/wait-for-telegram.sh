#!/bin/bash
# wait-for-telegram.sh — Anti-conflit 409
# Évite les conflits Telegram en utilisant un pidfile lock.
# Exécuté via ExecStartPre par systemd.

PIDFILE="/tmp/santana.pid"

if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[WAIT] Ancien processus Santana PID $OLD_PID toujours actif. Attente de sa mort..."
        # Attendre max 30s que l'ancien processus meure
        for i in $(seq 1 30); do
            if ! kill -0 "$OLD_PID" 2>/dev/null; then
                echo "[WAIT] Ancien processus mort après ${i}s."
                break
            fi
            sleep 1
        done
        # S'il est toujours vivant après 30s, le tuer
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "[WAIT] Force kill du PID $OLD_PID"
            kill -9 "$OLD_PID" 2>/dev/null
            sleep 1
        fi
    fi
fi

echo $$ > "$PIDFILE"
echo "[WAIT] PID $$ — lock pris."
exit 0
