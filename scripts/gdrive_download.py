#!/usr/bin/env python3
"""
Sideline Veille — Téléchargement depuis Google Drive
Récupère opportunites.json et seen_ids.json avant le run du scraper.
"""
import os
import json
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    import io
except ImportError:
    print("[GDRIVE] Bibliothèques Google non installées — skip")
    exit(0)

CREDENTIALS_JSON = os.environ.get("GDRIVE_CREDENTIALS", "")
FILE_ID          = os.environ.get("GDRIVE_FILE_ID", "")      # ID du fichier opportunites.json sur Drive
SEEN_FILE_ID     = os.environ.get("GDRIVE_SEEN_FILE_ID", "") # ID du fichier seen_ids.json sur Drive

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

def telecharger(service, file_id, destination):
    if not file_id:
        return
    try:
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = dl.next_chunk()
        Path(destination).write_bytes(buf.getvalue())
        print(f"[GDRIVE] Téléchargé → {destination}")
    except Exception as e:
        print(f"[GDRIVE] Impossible de télécharger {file_id}: {e}")

if __name__ == "__main__":
    service = get_service()
    if service:
        Path("data").mkdir(exist_ok=True)
        telecharger(service, FILE_ID, "data/opportunites.json")
        telecharger(service, SEEN_FILE_ID, "data/seen_ids.json")
