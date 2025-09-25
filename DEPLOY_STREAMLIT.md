# Déploiement GitHub + Streamlit Cloud

Pour que tout s'installe **automatiquement** sur Streamlit Cloud :

1. **Mettez ces fichiers à la racine du repo :**
   - `app.py` (l'app Streamlit)
   - `image_scraper.py` (le module scraper)
   - `requirements.txt` (dépendances Python)
   - `runtime.txt` (version Python — optionnel mais recommandé)

2. **requirements.txt** – Streamlit installe tout seul :
```
streamlit
requests
beautifulsoup4
pillow
```
   *(Ajoutez d'autres libs si vous en avez besoin.)*

3. **runtime.txt** – pour figer la version Python (ex. 3.11) :
```
3.11
```

4. **Sur Streamlit Cloud**
   - Connectez le repo GitHub.
   - Choisissez `app.py` comme *Main file path*.
   - Déployez. L'installation des dépendances se fait toute seule à partir de `requirements.txt`.

## Bonnes pratiques
- Évitez de faire des `pip install` depuis le code à l'exécution – laissez Streamlit gérer via `requirements.txt`.
- Respectez `robots.txt` et le droit d’auteur. L’option *Ignorer robots.txt* est volontairement marquée comme déconseillée.
- Si vous scrapez massivement, ajoutez un petit `delay` et un `max` raisonnable.
