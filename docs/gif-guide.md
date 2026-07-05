# Recording Santana in action — GIF/screenshot guide

Pour ajouter un vrai GIF d'exécution dans le README :

## Option 1 : Capture terminal avec `asciinema` + `agg` (recommandé)

```bash
# Installer asciinema
pip install asciinema

# Installer agg (renderer GIF) — https://github.com/asciinema/agg
# Ou utiliser asciicast2gif

# Enregistrer une session
asciinema rec santana-demo.cast

# Dans le terminal :
cd ~/santana
python santana.py --mode terminal
# Tape "what are my open GitHub PRs?"
# Tape "search the web for latest AI agent news"
# Tape "remember that I prefer concise answers"
# Ctrl+D pour quitter

# Convertir en GIF
agg santana-demo.cast docs/assets/santana-terminal-demo.gif
```

## Option 2 : Capture Telegram avec `peek` (Linux)

```bash
sudo apt install peek
peek
# Sélectionner la zone avec la fenêtre Telegram
# Démarrer l'enregistrement
# Envoyer des messages à Santana sur Telegram
# Arrêter → sauvegarder dans docs/assets/santana-telegram-demo.gif
```

## Option 3 : Screenshot manuel

Prendre un screenshot de :
- La conversation Telegram avec Santana
- Le terminal avec le log de l'agent running

Sauvegarder dans `docs/assets/` et référencer dans le README.

## Ajout dans le README

Après avoir généré le GIF :

```markdown
<p align="center">
  <img src="docs/assets/santana-telegram-demo.gif" alt="Santana in action on Telegram" width="600">
</p>
```
