#!/usr/bin/env python3
"""
Sideline Conseil — Moteur de veille marchés sportifs v2
========================================================
Trois moteurs de détection :
  1. RSS/HTML  — flux officiels et sites de federations/institutions
  2. Google    — recherche par mots-cles sur tout le web (Google Custom Search API)
  3. LinkedIn  — veille signaux faibles via Google indexe sur LinkedIn

Configuration requise :
  EMAIL_CONFIG       -> identifiants Gmail (App Password)
  GOOGLE_API_KEY     -> cle API Google Custom Search (gratuite, 100 req/jour)
  GOOGLE_CX          -> ID moteur de recherche personnalise Google CSE

Usage :
  python scraper.py              # veille complete + email
  python scraper.py --test       # sans envoi email, genere preview HTML
  python scraper.py --only rss   # un seul moteur (rss | google | linkedin)
  Cron OVH :
  0 8 * * * /usr/bin/python3 /home/LOGIN/sideline/scraper.py >> /home/LOGIN/sideline/logs/cron.log 2>&1
"""

import json
import os
import re
import time
import smtplib
import hashlib
import logging
import argparse
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "opportunites.json"
SEEN_FILE = BASE_DIR / "data" / "seen_ids.json"
LOG_FILE  = BASE_DIR / "logs" / "scraper.log"

(BASE_DIR / "data").mkdir(exist_ok=True)
(BASE_DIR / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ── Identifiants a renseigner ─────────────────────────────────────────────────
EMAIL_CONFIG = {
    "expediteur":   os.environ.get("GMAIL_USER", ""),
    "mot_de_passe": os.environ.get("GMAIL_PASSWORD", ""),
    "destinataire": os.environ.get("GMAIL_DESTINATAIRE", ""),
    "smtp_host":    "smtp.gmail.com",
    "smtp_port":    587,
}

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CX      = os.environ.get("GOOGLE_CX", "")


# ─── MOTS-CLES ────────────────────────────────────────────────────────────────

KEYWORDS_SPORT = [
    "sport", "sportif", "sportive", "federation sportive", "ligue sportive",
    "club sportif", "olympique", "paralympique", "athlete", "competition",
    "stade", "evenement sportif", "pratique sportive", "sponsoring sportif",
    "mecenat sportif", "football", "rugby", "basketball", "volleyball",
    "tennis", "natation", "cyclisme", "handball", "judo", "athletisme",
    "esport", "e-sport", "paris 2024", "jeux olympiques", "jeux paralympiques",
    "cnosf", "cpsf", "drajes", "creps", "insep",
    "agence nationale du sport", "cnds", "lfp", "lnr", "ffr", "fff",
    "ffbb", "ffvb", "ffhandball", "ffnatation", "fftennis", "ffjudo",
]

KEYWORDS_METIER = [
    "affaires publiques", "public affairs", "conseil strategique",
    "strategie", "communication institutionnelle", "influence",
    "lobbying", "plaidoyer", "relations institutionnelles",
    "relations publiques", "accompagnement", "consultant", "prestataire",
    "expertise", "etude", "diagnostic", "positionnement", "marque",
    "image de marque", "gouvernance", "developpement", "rayonnement",
    "attractivite", "mecenat", "sponsoring", "partenariat strategique",
    "plan de communication", "strategie de communication",
    "intelligence economique", "veille strategique", "analyse",
    "appel d offres", "appel a projets", "marche public", "prestation",
    "mission de conseil", "mission d accompagnement",
]

SCORE_WEIGHTS = {
    "affaires publiques": 22, "public affairs": 20,
    "influence": 16, "lobbying": 16, "plaidoyer": 16,
    "conseil strategique": 14, "strategie": 10,
    "communication institutionnelle": 12, "communication": 8,
    "federation": 12, "federation sportive": 15,
    "sponsoring": 12, "mecenat": 12,
    "sport": 5, "conseil": 8,
    "cnosf": 15, "agence nationale du sport": 15,
    "olympique": 10, "paralympique": 10,
    "appel d offres": 10, "appel a projets": 8,
    "partenariat strategique": 12,
}

SCORE_MINIMUM = 25


# ─── REQUETES GOOGLE ──────────────────────────────────────────────────────────
# Format : (requete, type_source, label)
# Budget : 100 req/jour gratuites -> max ~15 requetes/run
GOOGLE_QUERIES = [
    # Marches publics sport + conseil
    ("appel offres sport conseil communication", "marche-public", "Google — AO sport/conseil"),
    ("appel offres federation sportive prestataire", "federation", "Google — AO federations"),
    ("appel projets sport strategie influence 2026", "federation", "Google — AAP sport strategie"),
    ("marche public sport affaires publiques", "marche-public", "Google — MP affaires publiques"),
    # Institutions publiques sport
    ("appel offres site:agencedusport.fr", "marche-public", "Google — ANS"),
    ("appel offres appel projets site:franceolympique.com", "federation", "Google — CNOSF"),
    ("appel offres site:sports.gouv.fr", "marche-public", "Google — Ministere Sports"),
    ("avis marche sport conseil communication site:boamp.fr", "marche-public", "Google — BOAMP sport"),
    # Federations
    ("appel offres site:ffr.fr OR site:fff.fr OR site:ffbb.com", "federation", "Google — FFR/FFF/FFBB"),
    ("appel offres site:ffhandball.fr OR site:ffvb.org", "federation", "Google — FFH/FFV"),
    ("appel offres site:lnr.fr OR site:lfp.fr", "prive", "Google — LNR/LFP"),
    # Signaux prives
    ("recherche prestataire expression besoin sport strategie conseil", "prive", "Google — Signaux prives"),
    ("nous recherchons agence conseil sport communication 2026", "prive", "Google — Signaux agence"),
    # Collectivites
    ("appel offres collectivite sport communication strategie 2026", "marche-public", "Google — Collectivites"),
    ("appel projets sport region departement conseil accompagnement 2026", "marche-public", "Google — Regions"),
]

# ─── REQUETES LINKEDIN ────────────────────────────────────────────────────────
LINKEDIN_QUERIES = [
    "appel offres sport conseil communication federation",
    "recherche prestataire strategie sport federation",
    "expression besoin agence sport influence",
    "mission conseil sport affaires publiques",
    "appel offres sponsoring sport entreprise",
]

# ─── SOURCES RSS/HTML ─────────────────────────────────────────────────────────
SOURCES = [

    # ── MARCHES PUBLICS — Flux RSS CPV ───────────────────────────────────────
    {
        "id": "boamp_conseil",
        "label": "BOAMP — Conseil & communication (CPV 79)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=79000000",
        "parser": "rss",
    },
    {
        "id": "boamp_rd",
        "label": "BOAMP — R&D & etudes (CPV 73)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=73000000",
        "parser": "rss",
    },
    {
        "id": "boamp_sport",
        "label": "BOAMP — Services sportifs (CPV 92)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=92000000",
        "parser": "rss",
    },
    {
        "id": "ted_sport",
        "label": "TED/JOUE — Sport & conseil (EU)",
        "type": "marche-public",
        "url": "https://ted.europa.eu/api/latest/notice/-/rss?q=sport+conseil+communication&scope=0&language=fr",
        "parser": "rss",
    },
    {
        "id": "francemarches_sport",
        "label": "France Marches — Sport & conseil",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=sport+conseil+communication",
        "parser": "rss",
    },
    {
        "id": "francemarches_sponsoring",
        "label": "France Marches — Sponsoring sportif",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=sponsoring+sportif",
        "parser": "rss",
    },

    # ── INSTITUTIONS SPORTIVES NATIONALES ────────────────────────────────────
    {
        "id": "cnosf",
        "label": "CNOSF — Appels offres & projets",
        "type": "federation",
        "url": "https://www.franceolympique.com/cat/26-appels_d_offres.html",
        "parser": "html",
        "selector": "article, .news-item, .actu-item, li.item",
        "title_sel": "h2, h3, .titre, a",
        "desc_sel": "p, .chapeau, .resume",
        "link_sel": "a",
    },
    {
        "id": "agence_sport",
        "label": "Agence Nationale du Sport",
        "type": "marche-public",
        "url": "https://agencedusport.fr/appels-offres",
        "parser": "html",
        "selector": ".views-row, article, .field-content",
        "title_sel": "h2, h3, .views-field-title",
        "desc_sel": "p, .views-field-body",
        "link_sel": "a",
    },
    {
        "id": "ministere_sports",
        "label": "Ministere des Sports",
        "type": "marche-public",
        "url": "https://www.sports.gouv.fr/appels-a-projets",
        "parser": "html",
        "selector": "article, .node, .card",
        "title_sel": "h2, h3, h1",
        "desc_sel": "p, .field-body",
        "link_sel": "a",
    },

    # ── FEDERATIONS SPORTIVES ─────────────────────────────────────────────────
    {
        "id": "ffr",
        "label": "FFR — Federation Francaise de Rugby",
        "type": "federation",
        "url": "https://www.ffr.fr/ffr/publications-officielles/avis-dappel-a-la-concurrence",
        "parser": "html",
        "selector": "article, .card, .publication-item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "fff",
        "label": "FFF — Federation Francaise de Football",
        "type": "federation",
        "url": "https://www.fff.fr/la-federation/appels-doffres",
        "parser": "html",
        "selector": "article, .item, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffbb",
        "label": "FFBB — Federation Francaise de Basketball",
        "type": "federation",
        "url": "https://www.ffbb.com/ffbb/federation/appels-offres",
        "parser": "html",
        "selector": "article, .news, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffhandball",
        "label": "FFHandball — Federation Francaise de Handball",
        "type": "federation",
        "url": "https://www.ffhandball.fr/appels-offres/",
        "parser": "html",
        "selector": "article, .post, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffvolley",
        "label": "FFVolley — Federation Francaise de Volleyball",
        "type": "federation",
        "url": "https://www.ffvb.org/la-federation/appels-doffres",
        "parser": "html",
        "selector": "article, .item, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffnatation",
        "label": "FFN — Federation Francaise de Natation",
        "type": "federation",
        "url": "https://www.ffnatation.fr/webffn/appels-offres.php",
        "parser": "html",
        "selector": "article, .actualite, .card, tr",
        "title_sel": "h2, h3, td",
        "desc_sel": "p, td",
        "link_sel": "a",
    },
    {
        "id": "fftennis",
        "label": "FFT — Federation Francaise de Tennis",
        "type": "federation",
        "url": "https://www.fft.fr/la-fft/appels-doffres",
        "parser": "html",
        "selector": "article, .card, .item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffjudo",
        "label": "FFJudo — Federation Francaise de Judo",
        "type": "federation",
        "url": "https://www.ffjudo.com/la-federation/appels-offres",
        "parser": "html",
        "selector": "article, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffr13",
        "label": "FFR XIII — Rugby a XIII",
        "type": "federation",
        "url": "https://www.ffr13.fr/category/appels-doffres/",
        "parser": "html",
        "selector": "article, .post",
        "title_sel": "h2, h3",
        "desc_sel": "p, .excerpt",
        "link_sel": "a",
    },
    {
        "id": "ffathlétisme",
        "label": "FFA — Federation Francaise d Athletisme",
        "type": "federation",
        "url": "https://www.athle.fr/asp.net/main.html/html.aspx?htmlid=1",
        "parser": "html",
        "selector": "article, .news-item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },

    # ── LIGUES PROFESSIONNELLES ───────────────────────────────────────────────
    {
        "id": "lfp",
        "label": "LFP — Ligue de Football Professionnel",
        "type": "prive",
        "url": "https://www.lfp.fr/institutionnel/appels-offres",
        "parser": "html",
        "selector": "article, .card, .item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "lnr",
        "label": "LNR — Ligue Nationale de Rugby",
        "type": "prive",
        "url": "https://www.lnr.fr/la-ligue/appels-offres",
        "parser": "html",
        "selector": "article, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },

    # ── GRANDES COLLECTIVITES ─────────────────────────────────────────────────
    {
        "id": "idf_sport",
        "label": "Region Ile-de-France — Sport",
        "type": "marche-public",
        "url": "https://www.iledefrance.fr/appels-projets-appels-offres",
        "parser": "html",
        "selector": ".views-row, article, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "paris_marches",
        "label": "Ville de Paris — Marches publics",
        "type": "marche-public",
        "url": "https://www.paris.fr/pages/appels-d-offres-de-la-ville-de-paris-4992",
        "parser": "html",
        "selector": "article, .card, .list-item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
]


# ─── PARSERS ─────────────────────────────────────────────────────────────────

def parse_rss(source):
    items = []
    try:
        feed = feedparser.parse(source["url"])
        log.info(f"[RSS] {source['label']} -> {len(feed.entries)} entrees")
        for entry in feed.entries:
            items.append({
                "title":            entry.get("title", ""),
                "description":      entry.get("summary", entry.get("description", "")),
                "lien":             entry.get("link", ""),
                "date_publication": entry.get("published", ""),
                "source_id":        source["id"],
                "source_label":     source["label"],
                "type_source":      source["type"],
                "moteur":           "rss",
            })
    except Exception as e:
        log.warning(f"[RSS] Erreur {source['label']}: {e}")
    return items


def parse_html(source):
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SidelineVeille/2.0)"}
        r = requests.get(source["url"], headers=headers, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(source.get("selector", "article"))
        log.info(f"[HTML] {source['label']} -> {len(cards)} blocs")
        for card in cards[:30]:
            title_el = card.select_one(source.get("title_sel", "h2"))
            desc_el  = card.select_one(source.get("desc_sel", "p"))
            link_el  = card.select_one(source.get("link_sel", "a"))
            title = title_el.get_text(strip=True) if title_el else ""
            desc  = desc_el.get_text(strip=True)  if desc_el  else ""
            href  = link_el.get("href", "")        if link_el  else ""
            if href and not href.startswith("http"):
                base = "/".join(source["url"].split("/")[:3])
                href = base + ("" if href.startswith("/") else "/") + href
            if title:
                items.append({
                    "title":            title,
                    "description":      desc,
                    "lien":             href,
                    "date_publication": datetime.now().strftime("%Y-%m-%d"),
                    "source_id":        source["id"],
                    "source_label":     source["label"],
                    "type_source":      source["type"],
                    "moteur":           "html",
                })
    except Exception as e:
        log.warning(f"[HTML] Erreur {source['label']}: {e}")
    return items


# ─── MODULE 2 — GOOGLE CUSTOM SEARCH ─────────────────────────────────────────

def recherche_google(query, label, type_source, nb_results=10):
    """
    Interroge l'API Google Custom Search.
    Gratuit : 100 requetes/jour, 10 resultats/requete.
    Doc : https://developers.google.com/custom-search/v1/using_rest
    """
    items = []
    if GOOGLE_API_KEY == "VOTRE_CLE_API_GOOGLE":
        log.warning("[GOOGLE] Cle API non configuree — module desactive")
        return items
    params = {
        "key":          GOOGLE_API_KEY,
        "cx":           GOOGLE_CX,
        "q":            query,
        "num":          min(nb_results, 10),
        "lr":           "lang_fr",
        "dateRestrict": "m3",   # 3 derniers mois
    }
    try:
        r = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=15)
        r.raise_for_status()
        resultats = r.json().get("items", [])
        log.info(f"[GOOGLE] '{query[:50]}' -> {len(resultats)} resultats")
        for res in resultats:
            items.append({
                "title":            res.get("title", ""),
                "description":      res.get("snippet", ""),
                "lien":             res.get("link", ""),
                "date_publication": datetime.now().strftime("%Y-%m-%d"),
                "source_id":        f"google_{hashlib.md5(query.encode()).hexdigest()[:6]}",
                "source_label":     label,
                "type_source":      type_source,
                "moteur":           "google",
            })
        time.sleep(0.5)
    except Exception as e:
        log.warning(f"[GOOGLE] Erreur '{query[:40]}': {e}")
    return items


def lancer_google():
    tous = []
    for query, type_src, label in GOOGLE_QUERIES:
        tous.extend(recherche_google(query, label, type_src))
    log.info(f"[GOOGLE] Total : {len(tous)} resultats bruts")
    return tous


# ─── MODULE 3 — LINKEDIN (via Google) ────────────────────────────────────────

def lancer_linkedin():
    """
    Detecte les signaux LinkedIn via Google (site:linkedin.com/posts).
    Ne necessite pas de compte LinkedIn.
    Pour une extraction plus fiable, envisager Phantombuster (phantombuster.com).
    """
    tous = []
    for query in LINKEDIN_QUERIES:
        query_google = f"site:linkedin.com/posts {query}"
        items = recherche_google(
            query_google,
            label=f"LinkedIn — {query[:40]}",
            type_source="prive",
            nb_results=5,
        )
        for item in items:
            item["source_id"]    = f"linkedin_{hashlib.md5(query.encode()).hexdigest()[:6]}"
            item["source_label"] = "LinkedIn (signal)"
            item["moteur"]       = "linkedin"
        tous.extend(items)
        time.sleep(1)
    log.info(f"[LINKEDIN] Total : {len(tous)} signaux bruts")
    return tous


# ─── SCORING & FILTRAGE ───────────────────────────────────────────────────────

def nettoyer(texte):
    return re.sub(r"<[^>]+>", " ", texte).lower()

def scorer(item):
    corpus = nettoyer(item.get("title","") + " " + item.get("description",""))
    if not any(kw in corpus for kw in KEYWORDS_SPORT):
        return 0
    if not any(kw in corpus for kw in KEYWORDS_METIER):
        return 0
    score = 30
    for kw, poids in SCORE_WEIGHTS.items():
        if kw in corpus:
            score += poids
    if item.get("moteur") in ("google","linkedin"):
        score = min(score + 5, 100)
    return min(score, 100)

def deduire_types(item):
    corpus = nettoyer(item.get("title","") + " " + item.get("description",""))
    types = []
    if any(k in corpus for k in ["affaires publiques","lobbying","plaidoyer","institutionnel","parlement","ministere","public affairs"]):
        types.append("affaires-publiques")
    if any(k in corpus for k in ["strategie","positionnement","developpement","gouvernance","diagnostic"]):
        types.append("strategie")
    if any(k in corpus for k in ["communication","marque","image","notoriete","medias","presse","digitale"]):
        types.append("communication")
    if any(k in corpus for k in ["influence","rayonnement","attractivite","reputation","relations publiques"]):
        types.append("influence")
    return types or ["strategie"]

def generer_id(item):
    return hashlib.md5((item.get("title","") + item.get("source_id","")).encode()).hexdigest()[:12]

def est_urgent(date_limite):
    if not date_limite:
        return False
    try:
        return (datetime.strptime(str(date_limite)[:10], "%Y-%m-%d") - datetime.now()).days <= 15
    except Exception:
        return False

def formater_opportunite(item, score):
    moteur = item.get("moteur","rss")
    label  = item.get("source_label","")
    return {
        "id":              generer_id(item),
        "title":           item.get("title",""),
        "source":          item.get("type_source","marche-public"),
        "sourceLabel":     label,
        "moteur":          moteur,
        "types":           deduire_types(item),
        "secteur":         "Sport",
        "emetteur":        label,
        "typeEmetteur":    "Detection automatique",
        "description":     item.get("description","")[:500],
        "datePublication": str(item.get("date_publication", datetime.now().strftime("%Y-%m-%d")))[:10],
        "dateLimite":      None,
        "budget":          "A determiner",
        "contact":         "",
        "lien":            item.get("lien",""),
        "nouvelle":        True,
        "urgent":          False,
        "score":           score,
        "angles":          [],
        "source_auto":     True,
    }


# ─── PERSISTANCE ─────────────────────────────────────────────────────────────

def charger_donnees():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def sauvegarder_donnees(opps):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(opps, f, ensure_ascii=False, indent=2)
    log.info(f"Donnees sauvegardees -> {DATA_FILE} ({len(opps)} opportunites)")

def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def sauvegarder_vus(ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f)


# ─── EMAIL ───────────────────────────────────────────────────────────────────

EMAIL_TEMPLATE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<style>
  body{{font-family:Georgia,serif;background:#f5f2ee;margin:0;padding:0}}
  .wrap{{max-width:620px;margin:32px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
  .hdr{{background:#0d0d0d;padding:28px 32px}}
  .hdr h1{{color:#c8a86b;font-size:22px;margin:0 0 4px}}
  .hdr p{{color:#666;font-size:11px;margin:0;font-family:monospace;letter-spacing:1px}}
  .body{{padding:24px 32px}}
  .intro{{color:#555;font-size:14px;margin-bottom:24px;line-height:1.6}}
  .section-title{{font-size:10px;text-transform:uppercase;letter-spacing:2px;color:#999;margin:24px 0 12px;font-family:monospace}}
  .card{{border:1px solid #e0dbd4;border-radius:10px;padding:16px 18px;margin-bottom:12px}}
  .card-score{{float:right;color:#c8a86b;font-weight:bold;font-size:16px;font-family:monospace}}
  .card-title{{font-size:15px;font-weight:bold;color:#0d0d0d;margin:0 0 4px;line-height:1.3}}
  .card-meta{{font-size:10px;color:#aaa;font-family:monospace;margin-bottom:8px}}
  .card-desc{{font-size:12px;color:#666;line-height:1.55;margin-bottom:10px}}
  .btn{{display:inline-block;background:#c8a86b;color:#0d0d0d;padding:6px 14px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:bold}}
  .tag{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:9px;font-family:monospace;margin-right:3px}}
  .tag-urgent{{background:#b84040;color:white}}
  .tag-ap{{background:#e8f0fd;color:#2a5ab8}}
  .tag-strat{{background:#fdf4e8;color:#a06820}}
  .tag-com{{background:#f0e8fd;color:#7a30b8}}
  .tag-google{{background:#e8fdf0;color:#1a6040}}
  .tag-li{{background:#e8f4fd;color:#0a66c2}}
  .footer{{background:#f5f2ee;padding:14px 32px;font-size:10px;color:#aaa;font-family:monospace}}
</style></head><body>
<div class="wrap">
  <div class="hdr">
    <h1>Sideline Veille</h1>
    <p>RAPPORT {date} -- {nb_nouvelles} NOUVELLES OPPORTUNITES -- {nb_total} AU TOTAL</p>
  </div>
  <div class="body">
    <p class="intro">Bonjour Cyril,<br><br>
    <strong>{nb_nouvelles} nouvelles opportunites</strong> detectees &mdash; dont
    <strong>{nb_urgentes} urgente(s)</strong> (echeance &le;15j),
    <strong>{nb_google}</strong> via Google et
    <strong>{nb_linkedin}</strong> via LinkedIn.</p>
    {sections}
  </div>
  <div class="footer">Sideline Conseil &middot; Veille automatique &middot; {date}</div>
</div></body></html>"""

CARTE = """<div class="card">
  <div class="card-score">{score}</div>
  <div style="overflow:hidden">
    <div class="card-meta">{moteur_tag}{source} &middot; {date}</div>
    <div class="card-title">{title}</div>
    <div style="margin-bottom:8px">{tags}</div>
    <div class="card-desc">{desc}</div>
    {btn}
  </div>
</div>"""

def _carte(o):
    tags = ""
    for t in o.get("types",[]):
        m = {"affaires-publiques":"ap","strategie":"strat","communication":"com","influence":"ap"}
        tags += f'<span class="tag tag-{m.get(t,"strat")}">{t.upper()}</span>'
    if o.get("urgent"):
        tags += '<span class="tag tag-urgent">URGENT</span>'
    mot = o.get("moteur","rss")
    mtag = ""
    if mot == "google":
        mtag = '<span class="tag tag-google">GOOGLE</span> '
    elif mot == "linkedin":
        mtag = '<span class="tag tag-li">LINKEDIN</span> '
    btn = f'<a class="btn" href="{o["lien"]}">Voir</a>' if o.get("lien") else ""
    desc = o.get("description","")
    return CARTE.format(
        score=o["score"], moteur_tag=mtag,
        source=o.get("sourceLabel",""), date=o.get("datePublication",""),
        title=o["title"][:120], tags=tags,
        desc=(desc[:200]+"...") if len(desc)>200 else desc, btn=btn,
    )

def construire_email(nouvelles, total):
    nb_urgentes = sum(1 for o in nouvelles if o.get("urgent"))
    nb_google   = sum(1 for o in nouvelles if o.get("moteur")=="google")
    nb_linkedin = sum(1 for o in nouvelles if o.get("moteur")=="linkedin")
    urgentes  = [o for o in nouvelles if o.get("urgent")]
    rss_items = [o for o in nouvelles if o.get("moteur") in ("rss","html") and not o.get("urgent")]
    goo_items = [o for o in nouvelles if o.get("moteur")=="google"]
    li_items  = [o for o in nouvelles if o.get("moteur")=="linkedin"]
    sections = ""
    if urgentes:
        sections += '<div class="section-title">URGENTES -- Deadline dans 15 jours ou moins</div>'
        sections += "".join(_carte(o) for o in urgentes[:5])
    if rss_items:
        sections += '<div class="section-title">MARCHES PUBLICS & FEDERATIONS</div>'
        sections += "".join(_carte(o) for o in rss_items[:6])
    if goo_items:
        sections += '<div class="section-title">DETECTES VIA GOOGLE</div>'
        sections += "".join(_carte(o) for o in goo_items[:5])
    if li_items:
        sections += '<div class="section-title">SIGNAUX LINKEDIN</div>'
        sections += "".join(_carte(o) for o in li_items[:4])
    return EMAIL_TEMPLATE.format(
        date=datetime.now().strftime("%d/%m/%Y"),
        nb_nouvelles=len(nouvelles), nb_urgentes=nb_urgentes,
        nb_google=nb_google, nb_linkedin=nb_linkedin,
        nb_total=total, sections=sections,
    )

def envoyer_email(html, nouvelles):
    cfg = EMAIL_CONFIG
    nb_u = sum(1 for o in nouvelles if o.get("urgent"))
    sujet = f"[Sideline Veille] {len(nouvelles)} opportunites"
    if nb_u:
        sujet += f" -- {nb_u} urgente(s)"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = sujet
    msg["From"]    = cfg["expediteur"]
    msg["To"]      = cfg["destinataire"]
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as srv:
            srv.starttls()
            srv.login(cfg["expediteur"], cfg["mot_de_passe"])
            srv.sendmail(cfg["expediteur"], cfg["destinataire"], msg.as_string())
        log.info(f"Email envoye -> {cfg['destinataire']}")
    except Exception as e:
        log.error(f"Echec email : {e}")


# ─── ORCHESTRATEUR ────────────────────────────────────────────────────────────

def traiter_items(items, vus):
    nouvelles = []
    for item in items:
        uid = generer_id(item)
        if uid in vus:
            continue
        score = scorer(item)
        if score < SCORE_MINIMUM:
            continue
        opp = formater_opportunite(item, score)
        opp["urgent"] = est_urgent(opp.get("dateLimite"))
        nouvelles.append(opp)
        vus.add(uid)
    return nouvelles

def lancer_veille(test_mode=False, only=None):
    log.info("=" * 60)
    log.info("Sideline Veille v2 -- Demarrage")
    log.info("=" * 60)

    vus             = charger_vus()
    opps_existantes = charger_donnees()
    for o in opps_existantes:
        o["nouvelle"] = False

    nouvelles_opps = []

    # Moteur 1 : RSS / HTML
    if only in (None, "rss"):
        items_rss = []
        for source in SOURCES:
            if source["parser"] == "rss":
                items_rss.extend(parse_rss(source))
            elif source["parser"] == "html":
                items_rss.extend(parse_html(source))
        log.info(f"[RSS/HTML] {len(items_rss)} items bruts")
        nouvelles_opps.extend(traiter_items(items_rss, vus))

    # Moteur 2 : Google Custom Search
    if only in (None, "google"):
        items_google = lancer_google()
        nouvelles_opps.extend(traiter_items(items_google, vus))

    # Moteur 3 : LinkedIn (via Google)
    if only in (None, "linkedin"):
        items_li = lancer_linkedin()
        nouvelles_opps.extend(traiter_items(items_li, vus))

    log.info(f"Total nouvelles opportunites : {len(nouvelles_opps)}")

    toutes = nouvelles_opps + opps_existantes
    cutoff = datetime.now() - timedelta(days=90)
    toutes = [o for o in toutes if not o.get("source_auto") or
              datetime.strptime(o.get("datePublication","2000-01-01")[:10], "%Y-%m-%d") > cutoff]
    toutes = sorted(toutes, key=lambda x: x["score"], reverse=True)[:200]

    sauvegarder_donnees(toutes)
    sauvegarder_vus(vus)

    if nouvelles_opps and not test_mode:
        html = construire_email(nouvelles_opps, len(toutes))
        envoyer_email(html, nouvelles_opps)
    elif test_mode:
        log.info("Mode test -- email non envoye")
        if nouvelles_opps:
            preview = BASE_DIR / "logs" / "email_preview.html"
            preview.write_text(construire_email(nouvelles_opps, len(toutes)), encoding="utf-8")
            log.info(f"Preview -> {preview}")

    log.info(f"Veille terminee -- {len(toutes)} opportunites actives")
    return toutes


# ─── POINT D'ENTREE ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sideline Veille v2")
    ap.add_argument("--test", action="store_true", help="Sans envoi email")
    ap.add_argument("--only", choices=["rss","google","linkedin"], help="Un seul moteur")
    args = ap.parse_args()
    lancer_veille(test_mode=args.test, only=args.only)
