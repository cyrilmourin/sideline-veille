#!/usr/bin/env python3
"""
Sideline Veille — Sauvegarde sur Google Drive
Depose opportunites.json et seen_ids.json apres le run du scraper.
"""
import os
import json
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("[GDRIVE] Bibliotheques Google non installees — skip")
    exit(0)

CREDENTIALS_JSON = os.environ.get("GDRIVE_CREDENTIALS", "")
FILE_ID          = os.environ.get("GDRIVE_FILE_ID", "")
SEEN_FILE_ID     = os.environ.get("GDRIVE_SEEN_FILE_ID", "")
FOLDER_ID        = os.environ.get("GDRIVE_FOLDER_ID", "")

def get_service():
    if not CREDENTIALS_JSON:
        print("[GDRIVE] GDRIVE_CREDENTIALS non defini — skip")
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
        try:
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"[GDRIVE] Mis a jour -> {local_path} (id:{file_id})")
            return file_id
        except Exception as e:
            print(f"[GDRIVE] Erreur mise a jour {file_id}: {e}")
            return None
    else:
        meta = {
            "name": nom_fichier or Path(local_path).name,
            "parents": [folder_id] if folder_id else []
        }
        try:
            f = service.files().create(body=meta, media_body=media, fields="id").execute()
            new_id = f.get("id")
            service.permissions().create(
                fileId=new_id,
                body={"type": "anyone", "role": "reader"}
            ).execute()
            print(f"[GDRIVE] Cree -> {local_path} (id:{new_id})")
            print(f"[GDRIVE] URL : https://drive.google.com/uc?id={new_id}&export=download")
            return new_id
        except Exception as e:
            print(f"[GDRIVE] Erreur creation : {e}")
            return None

if __name__ == "__main__":
    service = get_service()
    if service:
        folder = FOLDER_ID
        uploader(service, "data/opportunites.json", FILE_ID, folder, "opportunites.json")
        uploader(service, "data/seen_ids.json", SEEN_FILE_ID, folder, "seen_ids.json")
