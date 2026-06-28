# 🆘 SINBAD — Urgences
bash ~/symbad/HEAL.sh
## Pannes fréquentes
### Service ne répond plus
sudo systemctl restart symbad
### Rollback code
cp ~/symbad/backups/snapshot-20260507-STABLE/symbad.py ~/symbad/symbad.py && sudo systemctl restart symbad
### Nouvelle version (safe)
cat > /tmp/symbad_new.py << 'XEOF'
<coller le nouveau code>
XEOF
bash ~/symbad/safe_edit.sh
### Disque plein
sudo journalctl --vacuum-time=2d && df -h /
### Tout gelé
sudo reboot
