#!/usr/bin/env python3
"""
Sideline Veille — Sauvegarde sur Google Drive
Dépose opportunites.json et seen_ids.json après le run du scraper.
L'interface HTML lira ensuite ce fichier via un lien de partage Drive.
"""
import os
import json
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("[GDRIVE] Bibliothèques Google non installées — skip")
    exit(0)

CREDENTIALS_JSON = os.environ.get("GDRIVE_CREDENTIALS", "")
FILE_ID          = os.environ.get("GDRIVE_FILE_ID", "")       # mise à jour d'un fichier existant
SEEN_FILE_ID     = os.environ.get("GDRIVE_SEEN_FILE_ID", "")
FOLDER_ID        = os.environ.get("GDRIVE_FOLDER_ID", "")     # si création d'un nouveau fichier

def get_service():
    if not CREDENTIALS_JSON:
        print("[GDRIVE] GDRIVE_CREDENTIALS non défini — skip")
        return None
    creds_dict = json.loads(CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def uploader(service, local_path, file_id=None, folder_id=None, nom_fichier=None):
    if not Path(local_path).exists():
        print(f"[GDRIVE] Fichier absent : {local_path}")
        return None

    media = MediaFileUpload(local_path, mimetype="application/json", resumable=False)

    if file_id:
        # Mise à jour d'un fichier existant
        try:
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"[GDRIVE] Mis à jour → {local_path} (id:{file_id})")
            return file_id
        except Exception as e:
            print(f"[GDRIVE] Erreur mise à jour {file_id}: {e}")
            return None
    else:
        # Création d'un nouveau fichier
        meta = {"name": nom_fichier or Path(local_path).name}
        if folder_id:
            meta["parents"] = [folder_id]
        try:
            f = service.files().create(body=meta, media_body=media, fields="id").execute()
            new_id = f.get("id")
            # Rendre le fichier accessible en lecture publique
            service.permissions().create(
                fileId=new_id,
                body={"type": "anyone", "role": "reader"}
            ).execute()
            print(f"[GDRIVE] Créé → {local_path} (id:{new_id})")
            print(f"[GDRIVE] URL directe : https://drive.google.com/uc?id={new_id}&export=download")
            return new_id
        except Exception as e:
            print(f"[GDRIVE] Erreur création : {e}")
            return None

if __name__ == "__main__":
    service = get_service()
    if service:
        uploader(service, "data/opportunites.json", FILE_ID, FOLDER_ID, "opportunites.json")
        uploader(service, "data/seen_ids.json", SEEN_FILE_ID, FOLDER_ID, "seen_ids.json")
