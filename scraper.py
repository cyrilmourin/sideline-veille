#!/usr/bin/env python3
"""
Sideline Conseil — Moteur de veille marches sportifs v4
========================================================
Trois moteurs de detection :
  1. RSS/HTML  — flux officiels BOAMP (CPV enrichis), federations, agregateurs
  2. SerpAPI   — 8 requetes Google/run, 2x/semaine (quota : 88/mois < 100 gratuit)
  3. LinkedIn  — 3 signaux faibles via SerpAPI (site:linkedin.com)

Sources Couche 1 (marches publics) :
  BOAMP CPV 79400000, 79340000, 79416000, 79000000, 73200000, 92600000
  TED/JOUE Europe
  France Marches (requetes Sideline enrichies)
  Maximilien IDF
  CNOSF plateforme marches
  COJOP Alpes 2030 + SOLIDEO (marches2030.org)

Sources Couche 2 (federations / acteurs sport) :
  FFR, FFF, FFBB, FFHandball, FFVolley, FFN, FFT, FFJudo, FFR XIII, FFA
  FF Handisport, FF Voile, FF Badminton, FF Gym, FF Montagne, FF Equitation

Sources Couche 3 (signaux de marche / medias sectoriels) :
  SportBusiness Club, SPORSORA, News Tank Sport, Le Cafe du Sport Biz
  LFP, LNR (communiques)

Usage :
  python scraper.py              # veille complete + email
  python scraper.py --test       # sans envoi email
  python scraper.py --only rss   # un seul moteur (rss | google | linkedin)
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

# ── Identifiants ──────────────────────────────────────────────────────────────
EMAIL_CONFIG = {
    "expediteur":   "cyrilmourin@gmail.com",
    "smtp_login":   os.environ.get("GMAIL_USER", ""),
    "mot_de_passe": os.environ.get("GMAIL_PASSWORD", ""),
    "destinataire": os.environ.get("GMAIL_DESTINATAIRE", ""),
    "smtp_host":    "smtp-relay.brevo.com",
    "smtp_port":    587,
}

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")


# ─── MOTS-CLES DE SCORING ────────────────────────────────────────────────────

# Groupe A — dimension sport (au moins 1 obligatoire)
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
    "sportbusiness", "sporsora", "news tank sport",
    # Termes indirects (missions sans le mot sport)
    "politique sportive", "attractivite territoriale", "rayonnement",
    "grand evenement", "candidature olympique",
]

# Groupe B — dimension metier Sideline (au moins 1 obligatoire)
KEYWORDS_METIER = [
    "affaires publiques", "public affairs", "conseil strategique",
    "strategie", "communication institutionnelle", "influence",
    "lobbying", "plaidoyer", "relations institutionnelles",
    "relations publiques", "relations presse", "accompagnement",
    "consultant", "prestataire", "expertise", "etude", "diagnostic",
    "positionnement", "marque", "image de marque", "gouvernance",
    "developpement", "rayonnement", "attractivite", "mecenat",
    "sponsoring", "partenariat strategique", "plan de communication",
    "strategie de communication", "intelligence economique",
    "veille strategique", "analyse", "amo", "assistance maitrise ouvrage",
    "appel d offres", "appel a projets", "marche public", "prestation",
    "mission de conseil", "mission d accompagnement",
    "audit", "schema directeur", "plan strategique",
]

# Mots a exclure (pour reduire le bruit travaux/fournitures)
KEYWORDS_EXCLUSION = [
    "travaux", "construction", "rehabilitation", "batiment",
    "gros oeuvre", "fourniture", "equipement sportif", "sol sportif",
    "gazon", "vestiaires", "piscine travaux", "stade travaux",
    "maintenance", "entretien", "nettoyage", "gardiennage",
]

# Poids de scoring
SCORE_WEIGHTS = {
    "affaires publiques": 22, "public affairs": 20,
    "influence": 16, "lobbying": 16, "plaidoyer": 16,
    "conseil strategique": 14, "strategie": 10,
    "communication institutionnelle": 12, "communication": 8,
    "relations presse": 12, "relations publiques": 10,
    "federation": 12, "federation sportive": 15,
    "sponsoring": 12, "mecenat": 12,
    "sport": 5, "conseil": 8,
    "cnosf": 15, "agence nationale du sport": 15,
    "olympique": 10, "paralympique": 10,
    "appel d offres": 10, "appel a projets": 8,
    "partenariat strategique": 12, "amo": 10,
    "audit": 8, "schema directeur": 10, "plan strategique": 10,
    "attractivite": 8, "rayonnement": 8,
}

SCORE_MINIMUM = 25


# ─── REQUETES SERPAPI ────────────────────────────────────────────────────────
# Budget SerpAPI gratuit : 100 recherches/mois
# 8 requetes/run x 2 runs/semaine x 4 semaines = 64/mois (confortable)
# Format : (requete, type_source, label)
GOOGLE_QUERIES = [
    # Marches publics sport + conseil (requetes combinées)
    ("sport federation conseil strategie prestation appel offres", "marche-public", "SerpAPI — Sport+conseil AO"),
    ("sport communication relations presse appel offres marche public", "marche-public", "SerpAPI — Sport+com AO"),
    ("site:lalettre.fr OR site:strategies.fr OR site:uefa.com OR site:olympics.com sport conseil communication strategie", "prive", "SerpAPI — Medias bloques sport"),
    # Institutions cles + Alpes 2030
    ("appel offres site:agencedusport.fr OR site:sports.gouv.fr OR site:marches2030.org", "marche-public", "SerpAPI — ANS+Ministere+2030"),
    # Signaux prives — entreprises cherchant agence sport
    ("recherche prestataire agence sport strategie communication conseil", "prive", "SerpAPI — Signaux prives"),
    ("sponsoring sportif mecenat sport strategie conseil prestataire entreprise", "prive", "SerpAPI — Sponsoring"),
    # Opportunites cachees (collectivites / territoire sans le mot sport)
    ("communication strategie attractivite territoire appel offres collectivite", "marche-public", "SerpAPI — Opportunites cachees"),
    # Clubs pro (signaux changement agence / besoin prestataire)
    ("PSG OM LOSC Stade Rennais RC Lens Stade Francais Red Star Paris FC Caen Le Havre Racing 92 agence conseil communication", "prive", "SerpAPI — Clubs pro"),
]

# ─── REQUETES LINKEDIN (via SerpAPI) ─────────────────────────────────────────
# 3 requetes/run — incluses dans le quota ci-dessus
LINKEDIN_QUERIES = [
    "site:linkedin.com recherche prestataire strategie sport federation",
    "site:linkedin.com expression besoin agence sport influence affaires publiques",
    "site:linkedin.com mission conseil sport communication sponsoring",
]


# ─── SOURCES RSS/HTML ─────────────────────────────────────────────────────────
SOURCES = [

    # ══════════════════════════════════════════════════════════════════════════
    # COUCHE 1 — MARCHES PUBLICS
    # ══════════════════════════════════════════════════════════════════════════

    # ── BOAMP — CPV enrichis (recommandation ChatGPT) ─────────────────────────
    # CPV 79400000 — Conseil en gestion (le plus important pour Sideline)
    {
        "id": "boamp_conseil_gestion",
        "label": "BOAMP — Conseil en gestion (CPV 794)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=79400000",
        "parser": "rss",
    },
    # CPV 79340000 — Communication / marketing
    {
        "id": "boamp_communication",
        "label": "BOAMP — Communication & marketing (CPV 7934)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=79340000",
        "parser": "rss",
    },
    # CPV 79416000 — Relations publiques
    {
        "id": "boamp_rp",
        "label": "BOAMP — Relations publiques (CPV 7941)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=79416000",
        "parser": "rss",
    },
    # CPV 79000000 — Services aux entreprises (large)
    {
        "id": "boamp_conseil",
        "label": "BOAMP — Services aux entreprises (CPV 79)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=79000000",
        "parser": "rss",
    },
    # CPV 73200000 — Etudes / conseil en R&D
    {
        "id": "boamp_etudes",
        "label": "BOAMP — Etudes & conseil (CPV 732)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=73200000",
        "parser": "rss",
    },
    # CPV 92600000 — Services sportifs
    {
        "id": "boamp_sport",
        "label": "BOAMP — Services sportifs (CPV 926)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=92600000",
        "parser": "rss",
    },
    # CPV 92000000 — Services recreatifs, culturels, sportifs (large)
    {
        "id": "boamp_recreatif",
        "label": "BOAMP — Services recreatifs & sportifs (CPV 92)",
        "type": "marche-public",
        "url": "https://www.boamp.fr/avis/flux-rss/?code_cpv=92000000",
        "parser": "rss",
    },
    # TED Europe
    {
        "id": "ted_sport",
        "label": "TED/JOUE — Sport & conseil (EU)",
        "type": "marche-public",
        "url": "https://ted.europa.eu/api/latest/notice/-/rss?q=sport+conseil+communication&scope=0&language=fr",
        "parser": "rss",
    },

    # ── FRANCE MARCHES — Agregateur principal ────────────────────────────────
    # Requete principale fournie par Cyril
    {
        "id": "francemarches_sideline",
        "label": "France Marches — Sport & conseil (requete Sideline)",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=%22sport%22+OU+%22sportif%22+OU+%22sportive%22+OU+%22Agence+Nationale+du+Sport%22+OU+%22Minist%C3%A8re+des+Sports%22&types%5B%5D=171&etat=en-cours",
        "parser": "rss",
    },
    # Communication sport
    {
        "id": "francemarches_com_sport",
        "label": "France Marches — Communication sport",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=sport+communication+OU+sport+%22relations+presse%22",
        "parser": "rss",
    },
    # Strategie sport
    {
        "id": "francemarches_strat_sport",
        "label": "France Marches — Strategie & conseil sport",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=sport+conseil+OU+sport+strat%C3%A9gie+OU+sport+%C3%A9tude",
        "parser": "rss",
    },
    # Sponsoring / mecenat
    {
        "id": "francemarches_sponsoring",
        "label": "France Marches — Sponsoring & mecenat sportif",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=sponsoring+sportif+OU+mecenat+sportif",
        "parser": "rss",
    },
    # Affaires publiques sport
    {
        "id": "francemarches_ap",
        "label": "France Marches — Affaires publiques sport",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=%22affaires+publiques%22+sport+OU+influence+sport",
        "parser": "rss",
    },
    # Opportunites cachees — sans le mot sport (attractivite, territoire)
    {
        "id": "francemarches_hors_sport",
        "label": "France Marches — Opportunites cachees (attractivite/territoire)",
        "type": "marche-public",
        "url": "https://www.francemarches.com/rss/appels-offres?q=%22attractivit%C3%A9%22+communication+OU+%22rayonnement%22+strat%C3%A9gie+OU+%22grand+%C3%A9v%C3%A9nement%22+communication",
        "parser": "rss",
    },

    # ── PLATEFORMES SPECIALISEES ──────────────────────────────────────────────
    # CNOSF — plateforme marches mouvement olympique
    {
        "id": "cnosf_marches",
        "label": "CNOSF — Plateforme marches publics",
        "type": "federation",
        "url": "https://cnosf.e-marchespublics.com/pack/recherche_d_appels_d_offres_marches_publics_1_aapc___service_____1.html",
        "parser": "html",
        "selector": "tr, .avis-item, article, .result-item",
        "title_sel": "td, h2, h3, a",
        "desc_sel": "td, p",
        "link_sel": "a",
        "timeout": 10,
    },
    # COJOP Alpes 2030 + SOLIDEO — plateforme commune marches JO hiver 2030
    {
        "id": "marches2030",
        "label": "Marches 2030 — COJOP + SOLIDEO Alpes",
        "type": "marche-public",
        "url": "https://www.marches2030.org/appels-offres",
        "parser": "html",
        "selector": "article, .card, .appel-offre, .consultation, tr",
        "title_sel": "h2, h3, td, a",
        "desc_sel": "p, td",
        "link_sel": "a",
        "timeout": 15,
    },
    # Agence Nationale du Sport — timeout depuis GitHub Actions, couverte par SerpAPI
    # {
    #     "id": "agence_sport",
    #     "url": "https://www.agencedusport.fr/marches-publics",
    # },
    # Maximilien IDF — sport + conseil
    {
        "id": "maximilien_sport",
        "label": "Maximilien IDF — Sport & conseil",
        "type": "marche-public",
        "url": "https://marches.maximilien.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllMots=sport+conseil&TypeMarche=S",
        "parser": "html",
        "selector": "tr.resultat, .avis, article, .marche-item",
        "title_sel": "td, h2, h3, a",
        "desc_sel": "td, p",
        "link_sel": "a",
        "timeout": 15,
    },
    # Maximilien IDF — communication sport
    {
        "id": "maximilien_com",
        "label": "Maximilien IDF — Sport & communication",
        "type": "marche-public",
        "url": "https://marches.maximilien.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllMots=sport+communication&TypeMarche=S",
        "parser": "html",
        "selector": "tr, .result, .avis, article",
        "title_sel": "td, h2, h3, a",
        "desc_sel": "td, p",
        "link_sel": "a",
        "timeout": 15,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # COUCHE 2 — FEDERATIONS SPORTIVES (pages consultations directes)
    # ══════════════════════════════════════════════════════════════════════════

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
        "url": "https://www.ffbb.com/consultations-mise-en-concurrence",
        "parser": "html",
        "selector": "article, .news, .card, .consultation",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffhandball",
        "label": "FFHandball — Consultations & appels a candidature",
        "type": "federation",
        "url": "https://www.ffhandball.fr/vie-federale/documentation/consultations-appels-a-candidature/",
        "parser": "html",
        "selector": "article, .post, .card, .document-item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffvolley",
        "label": "FFVolley — Consultations",
        "type": "federation",
        "url": "https://www.ffvb.org/360-37-1-CONSULTATIONS",
        "parser": "html",
        "selector": "article, .item, .card, tr",
        "title_sel": "h2, h3, td",
        "desc_sel": "p, td",
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
        "url": "https://www.fft.fr/consultations",
        "parser": "html",
        "selector": "article, .card, .item, .consultation",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffjudo",
        "label": "FFJudo — Consultations & appels offres",
        "type": "federation",
        "url": "https://www.ffjudo.com/consultations-et-appels-doffre",
        "parser": "html",
        "selector": "article, .card, .item",
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
        "id": "ffa",
        "label": "FFA — Federation Francaise d Athletisme",
        "type": "federation",
        "url": "https://www.athle.fr/actualites/",
        "parser": "html",
        "selector": "article, .news-item, .actu",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    # ── FEDERATIONS SUPPLEMENTAIRES ──────────────────────────────────────────
    {
        "id": "ffhandisport",
        "label": "FF Handisport — Consultations",
        "type": "federation",
        "url": "https://www.handisport.org/category/vie-federale/appels-doffres/",
        "parser": "html",
        "selector": "article, .card, .item, .post",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "ffvoile",
        "label": "FF Voile — Consultations",
        "type": "federation",
        "url": "https://www.ffvoile.fr/ffv/web/federation/appels_offres.aspx",
        "parser": "html",
        "selector": "article, .card, .item, tr",
        "title_sel": "h2, h3, td",
        "desc_sel": "p, td",
        "link_sel": "a",
    },
    {
        "id": "ffbad",
        "label": "FF Badminton — Consultations",
        "type": "federation",
        "url": "https://www.ffbad.org/la-federation/appels-doffres/",
        "parser": "html",
        "selector": "article, .card, .item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    # FFGym desactivee (500 Server Error)
    {
        "id": "ffme",
        "label": "FFME — Montagne & Escalade — Consultations",
        "type": "federation",
        "url": "https://www.ffme.fr/appels-doffre-consultations/",
        "parser": "html",
        "selector": "article, .card, .item, .post",
        "title_sel": "h2, h3",
        "desc_sel": "p, .excerpt",
        "link_sel": "a",
    },
    {
        "id": "ffe",
        "label": "FFE — Federation Francaise d Equitation — Consultations",
        "type": "federation",
        "url": "https://www.ffe.com/la-ffe/appels-offres",
        "parser": "html",
        "selector": "article, .card, .item",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # COUCHE 3 — MEDIAS SECTORIELS (signaux de marche)
    # ══════════════════════════════════════════════════════════════════════════

    # SportBusiness Club — media sectoriel sport business
    {
        "id": "sportbusiness_club",
        "label": "SportBusiness Club — Signaux marche",
        "type": "prive",
        "url": "https://www.sportbusiness.club/feed/",
        "parser": "rss",
    },
    # SPORSORA — federation marketing sportif
    {
        "id": "sporsora",
        "label": "SPORSORA — Marketing sportif",
        "type": "prive",
        "url": "https://www.sporsora.com/feed/",
        "parser": "rss",
    },
    # News Tank Sport — media pro sport business
    {
        "id": "newstank_sport",
        "label": "News Tank Sport — Actualites pro",
        "type": "prive",
        "url": "https://www.newstanksport.fr/rss/actualites/",
        "parser": "rss",
    },
    # Le Cafe du Sport Biz
    {
        "id": "cafe_sport_biz",
        "label": "Le Cafe du Sport Biz — Signaux",
        "type": "prive",
        "url": "https://www.lecafedusportbiz.fr/feed/",
        "parser": "rss",
    },
    # Strategies.fr — 403 bloque depuis GitHub Actions, couverte par SerpAPI
    # Kingcom — veille communication institutionnelle et publique (fonctionne)
    {
        "id": "kingcom_actu",
        "label": "Kingcom — Communication institutionnelle",
        "type": "prive",
        "url": "https://www.kingcom.fr/actualites/",
        "parser": "html",
        "selector": "article, .post, .card, .news",
        "title_sel": "h2, h3",
        "desc_sel": "p, .excerpt",
        "link_sel": "a",
        "timeout": 10,
    },
    # Strategies.fr — 403 bloque, desactive
    # La Lettre — 403 bloque, desactive
    # Sport Buzz Business — marketing sportif (fonctionne)
    {
        "id": "sportbuzzbusiness",
        "label": "Sport Buzz Business — Marketing sportif",
        "type": "prive",
        "url": "https://www.sportbuzzbusiness.fr/feed/",
        "parser": "rss",
    },
    # Sport Strategies — fonctionne
    {
        "id": "sport_strategies",
        "label": "Sport Strategies — Actualites sport business",
        "type": "prive",
        "url": "https://www.sportstrategies.com/actualite/",
        "parser": "html",
        "selector": "article, .post, .card, .news-item",
        "title_sel": "h2, h3, .entry-title",
        "desc_sel": "p, .excerpt, .entry-summary",
        "link_sel": "a",
        "timeout": 10,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # COUCHE 4 — ACTEURS INTERNATIONAUX (flux actualites — signaux faibles)
    # ══════════════════════════════════════════════════════════════════════════

    # CIO — 403 bloque, desactive
    # FIFA — URL inaccessible depuis GitHub Actions, desactivee
    # ANS — timeout depuis GitHub Actions, couverte par SerpAPI, desactivee
    # UEFA — timeout, desactivee
    # NBA — fonctionne
    {
        "id": "nba_news",
        "label": "NBA — Actualites",
        "type": "prive",
        "url": "https://www.nba.com/news",
        "parser": "html",
        "selector": "article, .ArticleTile, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p, .excerpt",
        "link_sel": "a",
        "timeout": 15,
    },
    # Roland Garros — fonctionne
    {
        "id": "roland_garros",
        "label": "Roland Garros — Actualites",
        "type": "prive",
        "url": "https://www.rolandgarros.com/fr-fr/article",
        "parser": "html",
        "selector": "article, .news-card, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p, .excerpt",
        "link_sel": "a",
        "timeout": 15,
    },
    # Tour de France ASO — URL corrigee
    {
        "id": "tour_de_france",
        "label": "Tour de France — Actualites ASO",
        "type": "prive",
        "url": "https://www.letour.fr/fr/news",
        "parser": "html",
        "selector": "article, .news-item, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p, .excerpt",
        "link_sel": "a",
        "timeout": 15,
    },
    # F1 — fonctionne
    {
        "id": "f1_news",
        "label": "F1 — Actualites",
        "type": "prive",
        "url": "https://www.formula1.com/en/latest/all.html",
        "parser": "html",
        "selector": "article, .article-card, .card",
        "title_sel": "h2, h3",
        "desc_sel": "p, .excerpt",
        "link_sel": "a",
        "timeout": 15,
    },

    # ── LIGUES PROFESSIONNELLES ───────────────────────────────────────────────
    {
        "id": "lfp",
        "label": "LFP — Ligue de Football Professionnel",
        "type": "prive",
        "url": "https://www.lfp.fr/?category=communiques",
        "parser": "html",
        "selector": "article, .card, .item, .communique",
        "title_sel": "h2, h3",
        "desc_sel": "p",
        "link_sel": "a",
    },
    {
        "id": "lnr",
        "label": "LNR — Ligue Nationale de Rugby",
        "type": "prive",
        "url": "https://www.lnr.fr/actualites/toutes",
        "parser": "html",
        "selector": "article, .card, .actu",
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
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SidelineVeille/3.0)"}
        r = requests.get(
            source["url"],
            headers=headers,
            timeout=source.get("timeout", 20),
            verify=source.get("verify_ssl", True)
        )
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


# ─── MODULE 2 — SERPAPI ───────────────────────────────────────────────────────

def recherche_serpapi(query, label, type_source, nb_results=10):
    """
    Interroge SerpAPI (Google Search).
    Gratuit : 100 recherches/mois.
    Doc : https://serpapi.com/search-api
    """
    items = []
    if not SERPAPI_KEY:
        log.warning("[SERPAPI] Cle non configuree — module desactive")
        return items
    params = {
        "q":       query,
        "api_key": SERPAPI_KEY,
        "hl":      "fr",
        "gl":      "fr",
        "num":     min(nb_results, 10),
        "tbs":     "qdr:m3",   # 3 derniers mois
    }
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=20)
        r.raise_for_status()
        resultats = r.json().get("organic_results", [])
        log.info(f"[SERPAPI] '{query[:50]}' -> {len(resultats)} resultats")
        for res in resultats:
            items.append({
                "title":            res.get("title", ""),
                "description":      res.get("snippet", ""),
                "lien":             res.get("link", ""),
                "date_publication": datetime.now().strftime("%Y-%m-%d"),
                "source_id":        f"serpapi_{hashlib.md5(query.encode()).hexdigest()[:6]}",
                "source_label":     label,
                "type_source":      type_source,
                "moteur":           "google",
            })
        time.sleep(1)
    except Exception as e:
        log.warning(f"[SERPAPI] Erreur '{query[:40]}': {e}")
    return items


def lancer_google():
    tous = []
    for query, type_src, label in GOOGLE_QUERIES:
        tous.extend(recherche_serpapi(query, label, type_src))
    log.info(f"[SERPAPI] Total : {len(tous)} resultats bruts")
    return tous


# ─── MODULE 3 — LINKEDIN (via SerpAPI) ───────────────────────────────────────

def lancer_linkedin():
    tous = []
    for query in LINKEDIN_QUERIES:
        items = recherche_serpapi(query, "LinkedIn (signal)", "prive", nb_results=5)
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

    # Exclusions — bruit travaux/fournitures
    nb_exclusions = sum(1 for kw in KEYWORDS_EXCLUSION if kw in corpus)
    if nb_exclusions >= 2:
        return 0

    if not any(kw in corpus for kw in KEYWORDS_SPORT):
        return 0
    if not any(kw in corpus for kw in KEYWORDS_METIER):
        return 0

    score = 30
    for kw, poids in SCORE_WEIGHTS.items():
        if kw in corpus:
            score += poids

    # Bonus moteur actif
    if item.get("moteur") in ("google", "linkedin"):
        score = min(score + 5, 100)

    return min(score, 100)

def deduire_types(item):
    corpus = nettoyer(item.get("title","") + " " + item.get("description",""))
    types = []
    if any(k in corpus for k in ["affaires publiques","lobbying","plaidoyer","institutionnel","parlement","ministere","public affairs","amo"]):
        types.append("affaires-publiques")
    if any(k in corpus for k in ["strategie","positionnement","developpement","gouvernance","diagnostic","audit","schema directeur"]):
        types.append("strategie")
    if any(k in corpus for k in ["communication","marque","image","notoriete","medias","presse","digitale","relations presse"]):
        types.append("communication")
    if any(k in corpus for k in ["influence","rayonnement","attractivite","reputation","relations publiques","lobbying"]):
        types.append("influence")
    return types or ["strategie"]

def generer_id(item):
    return hashlib.md5((item.get("title","") + item.get("source_id","")).encode()).hexdigest()[:12]

def _parse_date(date_str):
    """Parse une date quelle que soit son format RSS ou ISO."""
    if not date_str:
        return datetime(2000, 1, 1)
    s = str(date_str)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return datetime(2000, 1, 1)

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
  .section-title{{font-size:10px;text-transform:uppercase;letter-spacing:2px;color:#999;margin:24px 0 12px;font-family:monospace;border-bottom:1px solid #eee;padding-bottom:6px}}
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
    <p>RAPPORT {date} -- {nb_nouvelles} NOUVELLES -- {nb_total} AU TOTAL</p>
  </div>
  <div class="body">
    <p class="intro">Bonjour Cyril,<br><br>
    <strong>{nb_nouvelles} nouvelles opportunites</strong> detectees dont
    <strong>{nb_urgentes} urgente(s)</strong>,
    <strong>{nb_google}</strong> via Google/SerpAPI et
    <strong>{nb_linkedin}</strong> via LinkedIn.</p>
    {sections}
  </div>
  <div class="footer">Sideline Conseil &middot; Veille automatique v3 &middot; {date}</div>
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
        sections += '<div class="section-title">URGENTES — Deadline dans 15 jours ou moins</div>'
        sections += "".join(_carte(o) for o in urgentes[:5])
    if rss_items:
        sections += '<div class="section-title">MARCHES PUBLICS & FEDERATIONS</div>'
        sections += "".join(_carte(o) for o in rss_items[:8])
    if goo_items:
        sections += '<div class="section-title">DETECTES VIA GOOGLE (SerpAPI)</div>'
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
        sujet += f" — {nb_u} urgente(s)"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = sujet
    msg["From"]    = cfg["expediteur"]
    msg["To"]      = cfg["destinataire"]
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as srv:
            srv.starttls()
            srv.login(cfg["smtp_login"], cfg["mot_de_passe"])
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
    log.info("Sideline Veille v4 -- Demarrage")
    log.info("=" * 60)

    vus             = charger_vus()
    opps_existantes = charger_donnees()
    # Garder nouvelle:true pendant 48h, puis passer à False
    cutoff_nouvelle = datetime.now() - timedelta(hours=48)
    for o in opps_existantes:
        date_pub = _parse_date(o.get("datePublication","2000-01-01"))
        if date_pub < cutoff_nouvelle:
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

    # Moteur 2 : SerpAPI (Google)
    if only in (None, "google"):
        items_google = lancer_google()
        nouvelles_opps.extend(traiter_items(items_google, vus))

    # Moteur 3 : LinkedIn (via SerpAPI)
    if only in (None, "linkedin"):
        items_li = lancer_linkedin()
        nouvelles_opps.extend(traiter_items(items_li, vus))

    log.info(f"Total nouvelles opportunites : {len(nouvelles_opps)}")

    toutes = nouvelles_opps + opps_existantes
    cutoff = datetime.now() - timedelta(days=90)
    toutes = [o for o in toutes if not o.get("source_auto") or
              _parse_date(o.get("datePublication","2000-01-01")) > cutoff]
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
    ap = argparse.ArgumentParser(description="Sideline Veille v4")
    ap.add_argument("--test", action="store_true", help="Sans envoi email")
    ap.add_argument("--only", choices=["rss","google","linkedin"], help="Un seul moteur")
    args = ap.parse_args()
    lancer_veille(test_mode=args.test, only=args.only)
