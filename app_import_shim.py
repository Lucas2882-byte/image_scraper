import io
import os
import zipfile
import hashlib
import importlib
import sys

import streamlit as st

st.set_page_config(page_title="Image Scraper (Single URL)", page_icon="🖼️", layout="centered")
st.title("🖼️ Image Scraper — Single URL")
st.write("Scrape et télécharge les images d'une seule page web.")

# ---------- Import shim: tries several layouts ----------
# Supported layouts:
# 1) repo/
#    ├─ app.py
#    └─ image_scraper.py
# 2) repo/
#    └─ image_scraper/
#       ├─ app.py
#       └─ image_scraper.py
# 3) repo/
#    ├─ app.py
#    └─ scraper_utils.py  (alternative name)

HERE = os.path.dirname(__file__)
PARENT = os.path.abspath(os.path.join(HERE, ".."))
for p in (HERE, PARENT):
    if p not in sys.path:
        sys.path.insert(0, p)

def _try_import():
    # Try direct module next to the app
    candidates = [
        "image_scraper",              # image_scraper.py at root
        "scraper_utils",              # alternative filename
        "image_scraper.image_scraper" # subfolder package+module
    ]
    last_err = None
    for name in candidates:
        try:
            mod = importlib.import_module(name)
            # Validate expected attributes
            for attr in ("extract_image_urls", "fetch_html", "robots_allows", "DEFAULT_HEADERS"):
                getattr(mod, attr)
            return mod
        except Exception as e:
            last_err = e
    raise ModuleNotFoundError(f"Impossible d'importer le module scraper ({last_err})")

try:
    scraper = _try_import()
    extract_image_urls = scraper.extract_image_urls
    fetch_html = scraper.fetch_html
    robots_allows = scraper.robots_allows
    DEFAULT_HEADERS = scraper.DEFAULT_HEADERS
    # Optional helpers if present
    content_type_is_image = getattr(scraper, "content_type_is_image", None)
    infer_extension = getattr(scraper, "infer_extension", None)
    PIL_AVAILABLE = getattr(scraper, "PIL_AVAILABLE", False)
    Image = getattr(scraper, "Image", None)
    BytesIO = getattr(scraper, "BytesIO", None)
    same_domain_func = getattr(scraper, "same_domain", None)
except Exception as e:
    st.error(f"Erreur d'import du module scraper : {e}")
    st.info("Assurez-vous que **image_scraper.py** (ou **scraper_utils.py**) est présent **au même niveau** que app.py, "
            "ou placez-les tous deux dans un dossier et renommez ce dossier autrement que 'image_scraper'.")
    st.stop()

# ---------- Sidebar options ----------
with st.sidebar:
    st.header("Options")
    url = st.text_input("URL de la page", placeholder="https://exemple.com/article")
    out_dir = st.text_input("Dossier de sortie", value="images")
    max_images = st.number_input("Nombre max d'images", min_value=1, max_value=5000, value=500, step=50)
    delay = st.number_input("Délai entre téléchargements (sec)", min_value=0.0, max_value=5.0, value=0.3, step=0.1)
    timeout = st.number_input("Timeout HTTP (sec)", min_value=5, max_value=120, value=20, step=5)
    same_domain = st.checkbox("Limiter au même domaine", value=False)
    min_w = st.number_input("Largeur minimale (px, 0 pour désactiver)", min_value=0, max_value=12000, value=0, step=10)
    min_h = st.number_input("Hauteur minimale (px, 0 pour désactiver)", min_value=0, max_value=12000, value=0, step=10)
    no_robots = st.checkbox("Ignorer robots.txt (déconseillé)", value=False)

col1, col2 = st.columns(2)
start = col1.button("🚀 Lancer le scraping", use_container_width=True)
clear = col2.button("🗑️ Vider le dossier", use_container_width=True)

log = st.empty()
progress = st.progress(0, text="En attente...")

def write_log(msg):
    log.text(msg)

def zip_folder(folder_path, zip_name="images.zip"):
    memzip = io.BytesIO()
    with zipfile.ZipFile(memzip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(folder_path):
            for f in files:
                fp = os.path.join(root, f)
                arc = os.path.relpath(fp, folder_path)
                zf.write(fp, arcname=arc)
    memzip.seek(0)
    return memzip

if clear and out_dir:
    try:
        if os.path.isdir(out_dir):
            for root, _, files in os.walk(out_dir, topdown=False):
                for f in files:
                    os.remove(os.path.join(root, f))
            write_log(f"Dossier vidé : {out_dir}")
        else:
            write_log("Aucun dossier à vider.")
    except Exception as e:
        st.error(f"Erreur pendant le nettoyage : {e}")

if start:
    if not url:
        st.error("Merci de saisir une URL.")
        st.stop()

    try:
        if not no_robots:
            allowed = robots_allows(url, DEFAULT_HEADERS.get("User-Agent", ""))
            if not allowed:
                st.warning("robots.txt interdit ce scraping pour cet user-agent. Cochez 'Ignorer robots.txt' pour passer outre (non recommandé).")
                st.stop()

        write_log("Récupération de la page...")
        html = fetch_html(url, timeout=int(timeout))

        write_log("Extraction des URLs d'images...")
        img_urls = extract_image_urls(html, base_url=url)
        total = len(img_urls)
        if total == 0:
            st.warning("Aucune image candidate trouvée sur cette page.")
            st.stop()

        st.info(f"{total} image(s) candidate(s) trouvée(s). Téléchargement en cours...")

        # Download loop (inline to show progress)
        import requests
        os.makedirs(out_dir, exist_ok=True)
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        saved = 0
        for i, img_url in enumerate(img_urls, start=1):
            if saved >= max_images:
                break
            if same_domain and same_domain_func and not same_domain_func(url, img_url):
                progress.progress(min(i/total, 1.0), text=f"Filtré (hors domaine) {i}/{total}")
                continue
            try:
                resp = session.get(img_url, stream=True, timeout=int(timeout))
                if resp.status_code >= 400:
                    progress.progress(min(i/total, 1.0), text=f"HTTP {resp.status_code} : {i}/{total}")
                    continue

                content = resp.content

                # Determine extension
                if infer_extension:
                    ext = infer_extension(resp, img_url)
                else:
                    ext = ".jpg"

                # Optional Pillow dimension filter
                if PIL_AVAILABLE and (min_w or min_h) and Image is not None:
                    try:
                        from io import BytesIO as _BytesIO
                        im = Image.open(_BytesIO(content))
                        w, h = im.size
                        if (min_w and w < min_w) or (min_h and h < min_h):
                            progress.progress(min(i/total, 1.0), text=f"Petite image {w}x{h} — {i}/{total}")
                            continue
                    except Exception:
                        pass

                # Name and save
                h = hashlib.sha1(img_url.encode("utf-8")).hexdigest()[:12]
                filename = f"{saved+1:04d}_{h}{ext}"
                with open(os.path.join(out_dir, filename), "wb") as f:
                    f.write(content)

                saved += 1
                progress.progress(min(i/total, 1.0), text=f"Téléchargée {saved}/{max_images} (candidat {i}/{total})")
            except Exception as e:
                progress.progress(min(i/total, 1.0), text=f"Erreur: {e} — {i}/{total}")
                continue

        write_log(f"Terminé. {saved} image(s) sauvegardée(s) dans '{out_dir}'.")
        if saved > 0:
            memzip = zip_folder(out_dir, "images.zip")
            st.download_button("⬇️ Télécharger le ZIP", memzip, file_name="images.zip", mime="application/zip", use_container_width=True)
        else:
            st.warning("Aucune image sauvegardée.")

    except Exception as e:
        st.exception(e)
        st.stop()

st.markdown("---")
st.caption("Respectez les droits d’auteur et les fichiers robots.txt. Utilisation à vos risques et périls.")
