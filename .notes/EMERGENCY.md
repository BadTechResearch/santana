# 🆘 Santana — Urgences

## Pannes fréquentes

### Service ne répond plus
systemctl --user restart santana

### Rollback code
cp ~/santana/backups/snapshot-STABLE/santana.py ~/santana/santana.py && systemctl --user restart santana

### Nouvelle version (safe)
1. Créer un snapshot : cp -r ~/santana ~/santana-backup-$(date +%Y%m%d_%H%M)
2. Appliquer les modifications
3. Vérifier : cd ~/santana && venv_new/bin/python -c "compile(open('santana.py').read(), 'santana.py', 'exec')"
4. Redémarrer : systemctl --user restart santana

### Disque plein
journalctl --vacuum-time=2d && df -h /

### Tout gelé
sudo reboot
