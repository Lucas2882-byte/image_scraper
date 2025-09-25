# Image Scraper (single URL)

A small Python tool to scrape and download images from a single webpage URL.

## Install
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
python image_scraper.py --url "https://exemple.com/page" --out "./images" --max 500 --delay 0.3
```

Options utiles :
- `--same-domain` : ne garder que les images hébergées sur le même domaine que la page.
- `--min-width` / `--min-height` : filtrer par dimensions (nécessite Pillow).
- `--no-robots` : ignorer robots.txt (déconseillé).
- `--timeout` : délai d’expiration des requêtes HTTP (sec).
- `--max` : nombre maximum d’images à télécharger.
- `--delay` : délai entre téléchargements, pour éviter de surcharger le site.

## Dépendances
- requests
- beautifulsoup4
- pillow (optionnelle pour filtrer par dimensions)

## Bonnes pratiques
- Respecter les conditions d’utilisation et le droit d’auteur.
- Vérifier `robots.txt` du site (activé par défaut).
- Éviter de lancer sur des sites qui ne vous appartiennent pas ou sans autorisation.
