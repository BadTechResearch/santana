#!/bin/bash
# Script éphémère de redémarrage de session Telegram — généré et auto-exécuté
# le 18/06/2026 à la demande de Serge (process Hermès proc_f90593eebd69).
sleep 8
kill -9 -1099072 2>/dev/null
sleep 4
export PATH="$HOME/.local/bin:$PATH"
cd /home/user/santana
exec script -qec "claude --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions" /home/user/santana/.telegram_restart_output.log
