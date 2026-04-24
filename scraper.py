#!/usr/bin/env python3
"""
Sideline Conseil — Moteur de veille marches sportifs v6
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
import unicodedata
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
    # Inclusions FranceMarchés (Cyril) : sport, sportif, sportives, olympique
    "sport", "sportif", "sportive", "sportives", "sportifs",
    "olympique", "olympiques", "paralympique", "paralympiques",
    "federation sportive", "ligue sportive",
    "club sportif", "athlete", "competition",
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

# Mots a exclure
# Section A — exclusions FranceMarchés (Cyril, source de vérité)
# Section B — exclusions historiques travaux/fournitures (héritage v3)
# Tous les mots sont normalisés sans accents (cf nettoyer())
KEYWORDS_EXCLUSION = [
    # ── Section A : liste FranceMarchés Cyril ──────────────────────────────
    "prestations de transport",
    "transports scolaires", "transport scolaire",
    "periodiques",
    "location",
    "assurance",
    "conformite",
    "surveillance",
    "nettoyage",
    "exploitation",                              # couvre exploitation/gestion
    "gestion et a l exploitation",
    "exploitation et a la gestion",
    "relative a la gestion et a l exploitation",
    "ateliers collectifs",
    "ateliers de cours collectifs",
    "entretien",
    "maintenance",
    "organisation d activites",
    "maitrise d oeuvre",
    "moe",                                       # alias maîtrise d'œuvre
    # ── Section A bis : ajouts Cyril 2026-04-19 ────────────────────────────
    "titres de restauration",
    "titre de restauration",
    "restauration collective",
    "hebergement",
    "bafa",                                      # brevet d'aptitude animation
    "bafd",                                      # idem, directeur
    # ── Section B : exclusions héritage travaux/fournitures ────────────────
    "travaux", "construction", "rehabilitation", "batiment",
    "gros oeuvre", "fourniture", "equipement sportif", "sol sportif",
    "gazon", "vestiaires", "piscine travaux", "stade travaux",
    "gardiennage",
]

# Liste stricte d'exclusion FranceMarchés — utilisée par match_francemarches_strict()
# 1 seul match suffit à exclure (logique stricte, contrairement au scoring qui tolère <2 hits)
KEYWORDS_EXCLUSION_FM_STRICT = [
    "prestations de transport", "transports scolaires", "transport scolaire",
    "periodiques", "location", "assurance", "conformite", "surveillance",
    "nettoyage", "exploitation", "gestion et a l exploitation",
    "exploitation et a la gestion", "relative a la gestion et a l exploitation",
    "ateliers collectifs", "ateliers de cours collectifs",
    "entretien", "maintenance", "organisation d activites",
    "maitrise d oeuvre", "moe",
    # ─ ajouts Cyril 2026-04-19 ─
    "titres de restauration", "titre de restauration",
    "restauration collective", "hebergement",
    "bafa", "bafd",
]

# Inclusions FranceMarchés strictes — au moins 1 obligatoire
KEYWORDS_INCLUSION_FM_STRICT = [
    "sport", "sportif", "sportifs", "sportive", "sportives",
    "olympique", "olympiques",
]

# CPV prestations intellectuelles — bonus scoring
CPV_BONUS = {
    "79400000": 15, "79411000": 15, "79410000": 12,
    "79311000": 12, "73200000": 10, "71241000": 10,
    "92600000": 8,  "92610000": 8,
}

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
    "partenariat strategique": 12, "amo": 12,
    "audit": 8, "schema directeur": 12, "plan strategique": 10,
    "attractivite": 8, "rayonnement": 8,
    # Nouveaux termes ChatGPT
    "assistance a maitrise d ouvrage": 14,
    "plan d action sport": 12, "schema directeur sport": 15,
    "programmation sportive": 12, "diagnostic sportif": 12,
    "plan de developpement": 10, "expertise sport": 12,
    "gouvernance sportive": 14, "structuration": 10,
    "developpement international": 10, "coopération internationale": 8,
}

SCORE_MINIMUM = 20


# ─── SURPONDERATION DES SITES DE REFERENCE MARCHE ────────────────────────────
# Les sources marché public officielles (BOAMP, JOUE, profils acheteurs ANS,
# Solideo, Paris 2024, ministères) sont surpondérées car ce sont les vrais
# canaux d'appels d'offres formels. Les médias et signaux LinkedIn n'ont pas
# la même valeur (signaux faibles, à corroborer).
SOURCE_WEIGHT_BONUS = {
    # ── Marchés publics français — BOAMP (autorité de référence) ──────────
    "boamp_conseil_gestion":  25,   # CPV 79400 — coeur de cible Sideline
    "boamp_communication":    22,   # CPV 79340
    "boamp_rp":               20,   # CPV 79416
    "boamp_etudes":           18,   # CPV 73200
    "boamp_sport":            25,   # CPV 92600 — services sportifs
    "boamp_recreatif":        15,   # CPV 92000
    "boamp_conseil":          15,   # CPV 79 (large)
    "boamp_api_":             20,   # préfixe pour items issus de l'API ODS
    # ── Européen ──────────────────────────────────────────────────────────
    "ted_sport":              25,
    # ── Profils acheteurs prioritaires ────────────────────────────────────
    "marches2030":            30,   # COJOP Alpes 2030 + SOLIDEO
    "cnosf_marches":          25,
    "maximilien_sport":       18,
    "maximilien_com":         18,
    # ── Agrégateur France Marches (requêtes Sideline) ─────────────────────
    "francemarches_sideline":     22,
    "francemarches_com_sport":    20,
    "francemarches_strat_sport":  22,
    "francemarches_sponsoring":   18,
    "francemarches_ap":           22,
    "francemarches_hors_sport":   12,
}

# Mapping ministères / agences à surpondérer selon le source_label ou l'URL
# (utilisé par bonus_acheteur_etat() pour les items dont le source_id n'est pas
#  dans SOURCE_WEIGHT_BONUS mais dont le contenu mentionne un acheteur clé)
ACHETEURS_PRIORITAIRES = {
    "agence nationale du sport": 18,
    "agencedusport":             18,
    "ans":                       12,
    "solideo":                   25,
    "paris 2024":                20,
    "cojo paris 2024":           20,
    "alpes 2030":                25,
    "cojop":                     25,
    "ministere des sports":      18,
    "sports.gouv":               18,
    "ministere de l education":  10,
    "education.gouv":            10,
    "drajes":                    12,
    "creps":                     10,
    "insep":                     12,
    "cnosf":                     15,
    "cpsf":                      12,
}


# ═════════════════════════════════════════════════════════════════════════════
# v6 — REFONTE 3 CATÉGORIES
# ═════════════════════════════════════════════════════════════════════════════
# Cat.1 = MARCHÉS RÉELS (appels d'offres publics formels)
# Cat.2 = SIGNAUX CONTRATS (partenariats annoncés, AO gagnés)
# Cat.3 = VEILLE SPORT BUSINESS (flux RSS qualifiés, bruit de fond)

# ─── Whitelist des émetteurs locaux FR (cat.1 marchés) ────────────────────
WHITELIST_EMETTEURS_LOCAUX_FR = [
    # 13 régions métropolitaines
    "region ile de france", "region auvergne rhone alpes", "region provence alpes cote d azur",
    "region grand est", "region hauts de france", "region nouvelle aquitaine",
    "region occitanie", "region pays de la loire", "region normandie",
    "region bretagne", "region centre val de loire", "region bourgogne franche comte",
    "region corse",
    # Métropoles / grandes villes
    "ville de paris", "mairie de paris", "metropole du grand paris",
    "metropole europeenne de lille", "ville de lille",
    "metropole de lyon", "ville de lyon", "grand lyon",
    "metropole aix marseille provence", "ville de marseille",
    "rennes metropole", "ville de rennes",
    "bordeaux metropole", "ville de bordeaux",
    "toulouse metropole", "ville de toulouse",
    "metropole nice cote d azur", "ville de nice",
    "nantes metropole", "ville de nantes",
    "eurometropole de strasbourg", "ville de strasbourg",
    # Ministères / État
    "ministere des sports", "sports gouv", "sports.gouv",
    "ministere de l education", "premier ministre", "matignon", "elysee",
    "drajes", "creps", "insep",
    # Agences / organismes publics
    "agence nationale du sport", "agencedusport", " ans ",
    "cnosf", "comite national olympique", "cpsf", "comite paralympique",
    "afd", "agence francaise de developpement",
    # Organisateurs grands événements sport
    "solideo", "societe de livraison des ouvrages olympiques",
    "cojop", "alpes 2030", "marches2030", "marches 2030",
    "paris 2024", "cojo paris 2024",
    "uci 2027", "uci championnats 2027", "mondiaux uci",
    "mondial basket 2031", "fiba 2031",
    "euro 2028", "uefa euro 2028", "euro masculin 2028",
    "coupe du monde rugby 2027", "rwc 2027",
    "coupe du monde rugby feminine 2025",
    # Fédérations (préfixes génériques)
    "federation francaise", "ffr", "fff", "fft", "ffbb", "ffn", "ffa",
    "ffhb", "ffvb", "ffc", "ffjda", "ffboxe", "ffe",
    "ffvoile", "ffsa", "ffjudo", "ffesport",
    # Ligues professionnelles
    "ligue de football professionnel", "lfp", "ligue 1", "ligue 2",
    "ligue nationale de rugby", "lnr", "top 14",
    "ligue nationale de basket", "lnb",
    "ligue nationale de handball", "lnh",
    "ligue feminine de basket", "lfb",
]

# ─── Whitelist orgs institutionnelles (FR + internationales) ─────────────
WHITELIST_ORGS_INSTITUTIONNELLES = WHITELIST_EMETTEURS_LOCAUX_FR + [
    "cio", "comite international olympique", "ioc",
    "uefa", "fifa", "fiba", "ihf", "itf", "iaaf", "world athletics",
    "world rugby", "wru", "irb", "uci", "union cycliste internationale",
    "world sailing", "fei", "iihf",
    "commission europeenne", "parlement europeen", "conseil de l europe",
    "coe", "enoc", "european olympic committees",
]

# ─── Whitelist domaines autorisés pour scraps Google/LinkedIn ────────────
WHITELIST_DOMAINES_SCRAP = [
    "boamp.fr", "marches-publics.gouv.fr", "projets-achats.marches-publics.gouv.fr",
    "ted.europa.eu", "francemarches.com",
    "marches2030.org", "achats.cnosf.org", "cnosf.org",
    "maximilien.fr", "e-marchespublics.com",
    "sports.gouv.fr", "agencedusport.fr", "education.gouv.fr",
    "afd.fr", "diplomatie.gouv.fr",
    "solideo.fr", "paris2024.org", "alpes2030.fr",
    "ffr.fr", "fff.fr", "fft.fr", "ffbb.com", "ffn.fr",
    "lfp.fr", "lnr.fr", "lnb.com", "lnh.fr",
    "linkedin.com/company/", "linkedin.com/school/",
]

# ─── Mots-clés SIGNAUX CONTRATS (cat.2) ──────────────────────────────────
KEYWORDS_SIGNAUX_CONTRATS = [
    # Choix d'agence / prestataire
    "agence choisie par", "agence retenue par",
    "a confie sa communication a", "a confie ses relations publiques a",
    "a confie sa strategie d influence",
    "a confie ses relations institutionnelles",
    "retient l agence", "retenue pour accompagner", "retenu pour accompagner",
    "selectionne comme conseil", "selectionnee comme conseil",
    "recrute comme agence", "designe comme prestataire", "designee comme prestataire",
    "designe prestataire", "designee prestataire",
    # Remporte / gagne un AO
    "remporte l appel d offre", "a remporte l appel d offre",
    "remporte le marche", "a remporte le marche",
    "remporte la consultation", "a remporte la consultation",
    "attribution du marche a", "marche attribue a", "attributaire du marche",
    # Partenariats
    "nouveau partenaire officiel", "nouveau partenaire",
    "renouvelle son partenariat avec", "prolonge son partenariat avec",
    "officialise son partenariat", "devient partenaire de",
    "accompagnera desormais", "accompagnera la federation",
    # Mécénat / sponsoring signé
    "signe un contrat de sponsoring", "signe un accord de mecenat",
]

# ─── Exclusions NOMINATIONS RH (drop pour cat.3) ─────────────────────────
KEYWORDS_EXCLUSION_NOMINATIONS = [
    "nomination ", "nomme ", "nommee ",
    "nouveau directeur commercial", "nouvelle directrice commerciale",
    "nouveau directeur marketing", "nouvelle directrice marketing",
    "nouveau directeur general", "nouvelle directrice generale",
    "prise de fonction", "prend ses fonctions",
    "promu ", "promue ", "promus ", "promues ",
    "arrive a la tete de", "arrive a la direction",
    "quitte ses fonctions", "quitte son poste", "demission ",
]

# ─── Mapping source_id -> catégorie (1/2/3) ──────────────────────────────
SOURCE_CATEGORY = {
    # Cat.1 — MARCHÉS RÉELS
    "boamp_conseil_gestion":      1,
    "boamp_communication":        1,
    "boamp_rp":                   1,
    "boamp_etudes":               1,
    "boamp_sport":                1,
    "boamp_recreatif":            1,
    "boamp_conseil":              1,
    "boamp_api_":                 1,
    "ted_sport":                  1,
    "marches2030":                1,
    "cnosf_marches":              1,
    "maximilien_sport":           1,
    "maximilien_com":             1,
    "francemarches_sideline":     1,
    "francemarches_com_sport":    1,
    "francemarches_strat_sport":  1,
    "francemarches_sponsoring":   1,
    "francemarches_ap":           1,
    "francemarches_hors_sport":   1,
    # Cat.3 — VEILLE SPORT BUSINESS
    "sportbusiness_club":         3,
    "sportbusiness_club_signaux": 3,
    "cafe_sport_business":        3,
    "cafe_sport_biz":             3,
    "sporsora":                   3,
    "sporsora_actu":              3,
    "sport_strategies":           3,
    "newstank_sport":             3,
    "newstank_sport_home":        3,
    "cosmos":                     3,
    "gie_sport_expertise":        3,
    "lequipe_sport_business":     3,
    "kingcom_actu":               3,
}


# ─── REQUETES SERPAPI ────────────────────────────────────────────────────────
# Budget SerpAPI gratuit : 100 recherches/mois
# v5 (2026-04-19) : 3 GOOGLE + 1 LINKEDIN = 4 req/run
# 4 req × 5 j/sem (lundi-vendredi) × 4.35 sem = ~87/mois → marge ~13/mois
# Chaque requête a été fusionnée (OR syntaxe Google) pour couvrir davantage
# de sites avec moins d'appels. nb_results est monté à 10 (max gratuit).
# Format : (requete, type_source, label)
GOOGLE_QUERIES = [
    # 1. Marches publics consolides : tous sites institutionnels + CPV conseil/sport
    ("(site:agencedusport.fr OR site:sports.gouv.fr OR site:marches2030.org "
     "OR site:marches-publics.gouv.fr OR site:projets-achats.marches-publics.gouv.fr "
     "OR site:afd.fr OR site:e-marchespublics.com) "
     "sport conseil strategie communication gouvernance",
     "marche-public",
     "SerpAPI — Marches publics sport+conseil (fusion)"),
    # 2. Marches publics generaux sport (texte libre, sans restriction site:)
    ("sport federation conseil strategie communication sponsoring "
     "appel offres marche public prestation intellectuelle",
     "marche-public",
     "SerpAPI — Marches publics sport (texte)"),
    # 3. Signaux prives consolides : agences, sponsoring, medias sport
    ("(recherche prestataire agence OR sponsoring sportif OR mecenat sport "
     "OR site:lalettre.fr OR site:strategies.fr OR site:uefa.com OR site:olympics.com) "
     "sport conseil strategie communication federation entreprise",
     "prive",
     "SerpAPI — Signaux prives (agences+medias+sponsoring)"),
]

# ─── REQUETES LINKEDIN (via SerpAPI) ─────────────────────────────────────────
# 1 requete consolidee/run — incluse dans le budget 4 req/run
LINKEDIN_QUERIES = [
    "site:linkedin.com (recherche prestataire OR expression besoin OR mission conseil) "
    "sport federation agence strategie communication sponsoring affaires publiques",
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
        "url": "https://www.marches2030.org/",
        "parser": "html",
        "selector": ".views-row, article, .card, h3, .field--name-title",
        "title_sel": "h3, h2, a",
        "desc_sel": "p, .field--name-body, .views-field-body",
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
        "url": "https://www.fff.fr/728-les-consultations-de-la-fff.html",
        "parser": "html",
        "selector": "article, .item, .card, h2, h3, .consultation, p",
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
    # SPORSORA — categorie actualites (complement pour ne pas rater d'articles)
    {
        "id": "sporsora_actu",
        "label": "SPORSORA — Actualites",
        "type": "prive",
        "url": "https://sporsora.com/categorie/actualites/feed/",
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

    # ── v6 — Ajouts cat.3 veille sport business ─────────────────────────
    # Sport Stratégies — média conseil/communication sport
    {
        "id": "sport_strategies",
        "label": "Sport Stratégies",
        "type": "prive",
        "url": "https://www.sport-strategies.com/feed/",
        "parser": "rss",
    },
    # COSMOS — conseil social du mouvement sportif
    {
        "id": "cosmos",
        "label": "COSMOS — Mouvement sportif",
        "type": "prive",
        "url": "https://www.cosmos.asso.fr/feed/",
        "parser": "rss",
    },
    # GIE Sport Expertise
    {
        "id": "gie_sport_expertise",
        "label": "GIE Sport Expertise",
        "type": "prive",
        "url": "https://sportexpertise.com/feed/",
        "parser": "rss",
    },
    # L'Équipe — actualités sport (flux général, filtré ensuite)
    {
        "id": "lequipe_sport_business",
        "label": "L'Équipe — Sport Business",
        "type": "prive",
        "url": "https://www.lequipe.fr/rss/actu_rss.xml",
        "parser": "rss",
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



# ─── MODULE 4 — API BOAMP OpenDataSoft (sans clé, gratuit) ───────────────────
# Doc : https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/

BOAMP_API_URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"

# CPV pertinents pour Sideline
BOAMP_CPV_PI    = ["79400000","79411000","79410000","79311000","73200000","71241000"]
BOAMP_CPV_SPORT = ["92600000","92610000"]

# Mots-clés pour filtrage post-ingestion
BOAMP_KW_PI = [
    "conseil","accompagnement","amo","assistance à maîtrise d'ouvrage",
    "audit","diagnostic","stratégie","schéma directeur","programmation",
    "plan d'action","expertise","influence","affaires publiques",
    "communication","relations presse","sponsoring","mecenat",
]
BOAMP_KW_SPORT = [
    "sport","sportif","sportive","federation","olympique","paralympique",
    "gymnase","piscine","stade","pratique sportive","politique sportive",
]
BOAMP_KW_EXCLUDE = [
    "travaux","construction","maintenance","exploitation",
    "animation","fourniture","réhabilitation","nettoyage",
]

def _boamp_score(objet, description):
    """Score simplifié pour l'API BOAMP — complémentaire au scorer principal."""
    texte = (objet + " " + description).lower()
    score = 0
    if any(k in texte for k in BOAMP_KW_PI):    score += 3
    if any(k in texte for k in BOAMP_KW_SPORT): score += 2
    if any(k in texte for k in BOAMP_KW_EXCLUDE): score -= 3
    return score

def lancer_boamp_api():
    """
    Interroge l'API BOAMP OpenDataSoft (sans clé) en filtrant sur :
    - nature = Services
    - mots-clés sport + prestations intellectuelles
    - publications des 90 derniers jours
    """
    items = []
    date_min = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    # Requête ODSQL : appels d'offres de services + mots-clés métier Sideline
    where = (
        "nature=\"APPEL_OFFRE\" AND type_marche=\"SERVICES\" AND ("
        "objet LIKE \"conseil\" OR objet LIKE \"strategie\" OR "
        "objet LIKE \"communication\" OR objet LIKE \"accompagnement\" OR "
        "objet LIKE \"influence\" OR objet LIKE \"affaires publiques\" OR "
        "objet LIKE \"federation\" OR objet LIKE \"olympique\" OR "
        "objet LIKE \"sponsoring\" OR objet LIKE \"mecenat\" OR "
        "objet LIKE \"sport\" OR objet LIKE \"sportif\""
        f") AND dateparution >= \"{date_min}\""
    )

    params = {
        "where":    where,
        "order_by": "dateparution DESC",
        "limit":    100,
        "offset":   0,
    }

    try:
        r = requests.get(BOAMP_API_URL, params=params, timeout=20)
        r.raise_for_status()
        records = r.json().get("results", [])
        log.info(f"[BOAMP_API] {len(records)} annonces brutes")

        for rec in records:
            objet       = rec.get("objet", "") or ""
            description = rec.get("descripteur", "") or ""
            acheteur    = rec.get("nomacheteur", "") or ""
            date_pub    = (rec.get("dateparution", "") or "")[:10]
            lien        = rec.get("urlacheteur", "") or f"https://www.boamp.fr/avis/detail/{rec.get('id','')}"
            cpvs        = [c.get("code","") for c in (rec.get("cpv") or []) if c.get("code")]

            # Filtre : exclure si pas de lien avec nos métiers
            if _boamp_score(objet, description) < 2:
                continue

            items.append({
                "title":            objet[:200],
                "description":      f"{acheteur} — {description}"[:500],
                "lien":             lien,
                "date_publication": date_pub or datetime.now().strftime("%Y-%m-%d"),
                "source_id":        f"boamp_api_{hashlib.md5(objet.encode()).hexdigest()[:6]}",
                "source_label":     "BOAMP API — Services sport/conseil",
                "type_source":      "marche-public",
                "moteur":           "rss",
            })

    except Exception as e:
        log.warning(f"[BOAMP_API] Erreur : {e}")

    log.info(f"[BOAMP_API] {len(items)} annonces retenues")
    return items



def nettoyer(texte):
    """
    Normalise le texte pour le matching mot-clé :
    - retire le HTML
    - lowercase
    - supprime les accents (NFD + ascii)
    - normalise les apostrophes (' " ` → ' simple)
    Permet à un mot-clé "conformite" de matcher "conformité" dans le texte source,
    et à "maitrise d oeuvre" de matcher "maîtrise d'œuvre".
    """
    if not texte:
        return ""
    s = re.sub(r"<[^>]+>", " ", texte)
    s = s.lower()
    # Normaliser apostrophes/œ
    s = s.replace("'", " ").replace("’", " ").replace("`", " ").replace("ʼ", " ").replace("ʹ", " ").replace("′", " ")
    s = s.replace("œ", "oe").replace("æ", "ae")
    # Supprimer accents (NFD : décompose puis garde uniquement ASCII)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Compacter les espaces multiples
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ─── FILTRE STRICT FRANCE MARCHES ─────────────────────────────────────────────
def match_francemarches_strict(item):
    """
    Reproduit la logique d'alerte FranceMarchés telle qu'utilisée par Sideline.
    Inclusions : au moins 1 mot dans KEYWORDS_INCLUSION_FM_STRICT
    Exclusions : aucun mot dans KEYWORDS_EXCLUSION_FM_STRICT (1 hit suffit à drop)
    Retourne True si l'item passe le filtre FM strict, False sinon.

    À appliquer aux sources marché public formelles (BOAMP, TED, France Marches,
    profils acheteurs) — pour les médias / LinkedIn on garde le scoring tolérant.
    """
    corpus = nettoyer(item.get("title", "") + " " + item.get("description", ""))
    if not any(kw in corpus for kw in KEYWORDS_INCLUSION_FM_STRICT):
        return False
    if any(kw in corpus for kw in KEYWORDS_EXCLUSION_FM_STRICT):
        return False
    return True


def bonus_acheteur_etat(item):
    """Bonus de score si l'item mentionne un acheteur public prioritaire."""
    corpus = nettoyer(
        item.get("title", "") + " " + item.get("description", "") + " " +
        item.get("source_label", "") + " " + item.get("lien", "")
    )
    bonus = 0
    for keyword, pts in ACHETEURS_PRIORITAIRES.items():
        if keyword in corpus:
            bonus = max(bonus, pts)  # un seul bonus, le plus fort
    return bonus

# ─── CLASSIFIEUR 3 CATÉGORIES (v6) ───────────────────────────────────────
def is_institutional_result(item):
    """
    Pour les items scraps Google/LinkedIn : vérifie que la source est
    institutionnelle (domaine whitelisté OU mention d'org reconnue dans le
    texte). Empêche le bruit des posts LinkedIn de particuliers sans
    rattachement à une org sportive reconnue.
    """
    lien = (item.get("lien", "") or "").lower()
    for domain in WHITELIST_DOMAINES_SCRAP:
        if domain in lien:
            return True
    corpus = nettoyer(item.get("title", "") + " " + item.get("description", ""))
    for org in WHITELIST_ORGS_INSTITUTIONNELLES:
        if org in corpus:
            return True
    return False


def detect_signal_contrat(item):
    """Vrai si l'item matche un verbe conjugué de signal de contrat gagné (cat.2)."""
    corpus = nettoyer(item.get("title", "") + " " + item.get("description", ""))
    return any(kw in corpus for kw in KEYWORDS_SIGNAUX_CONTRATS)


def matches_nomination(item):
    """Vrai si l'item ressemble à une nomination RH (à drop pour cat.3)."""
    corpus = nettoyer(item.get("title", "") + " " + item.get("description", ""))
    return any(kw in corpus for kw in KEYWORDS_EXCLUSION_NOMINATIONS)


def categorize(item):
    """
    Retourne 1 (marche reel), 2 (signal contrat), 3 (veille) ou None (drop).
    """
    src_id  = item.get("source_id", "") or ""
    moteur  = item.get("moteur", "rss")
    typ_src = item.get("type_source", "")

    # 1. Mapping prioritaire
    if src_id in SOURCE_CATEGORY:
        cat_src = SOURCE_CATEGORY[src_id]
        # Cas spécial : cat.3 avec signal contrat -> requalifier cat.2
        if cat_src == 3 and detect_signal_contrat(item):
            return 2
        # Cas spécial : cat.3 + nomination -> drop
        if cat_src == 3 and matches_nomination(item):
            return None
        return cat_src

    # 2. Préfixes (ex: boamp_api_xxxxxx)
    for prefix, cat in SOURCE_CATEGORY.items():
        if prefix.endswith("_") and src_id.startswith(prefix):
            return cat

    # 3. Marchés publics non mappés -> cat.1
    if typ_src == "marche-public":
        return 1

    # 4. Scraps Google/LinkedIn : filtre institutionnel + classification
    if moteur in ("google", "linkedin"):
        if not is_institutional_result(item):
            return None
        corpus = nettoyer(item.get("title", "") + " " + item.get("description", ""))
        if detect_signal_contrat(item):
            return 2
        market_signals = ["appel d offre", "consultation", "marche public",
                          "mise en concurrence", "appel a candidature",
                          "avis de marche", "dialogue competitif"]
        if any(kw in corpus for kw in market_signals):
            return 1
        if matches_nomination(item):
            return None
        return 3

    # 5. Autres médias privés -> cat.3 par défaut
    if matches_nomination(item):
        return None
    return 3


def scorer(item):
    corpus = nettoyer(item.get("title","") + " " + item.get("description",""))
    src_id     = item.get("source_id", "")
    type_src   = item.get("type_source", "")

    # ─── 1. Filtre FranceMarchés STRICT pour les marchés publics ─────────
    # Sur les sources officielles de marchés publics (BOAMP, TED, France Marchés,
    # profils acheteurs), on applique la logique d'alerte FranceMarchés telle que
    # définie par Cyril : 1 mot d'exclusion suffit à drop, 1 mot d'inclusion
    # sport/olympique obligatoire.
    is_marche_public_source = (
        type_src == "marche-public" or
        src_id.startswith(("boamp_", "ted_", "francemarches_", "marches2030",
                           "cnosf_", "maximilien_"))
    )
    if is_marche_public_source and not match_francemarches_strict(item):
        return 0

    # ─── 2. Exclusions générales (logique tolérante : ≥2 hits = drop) ────
    # Pour les sources non-marché-public (médias, LinkedIn), on garde l'ancienne
    # logique : il faut ≥2 mots exclus pour drop, sinon on tolère.
    nb_exclusions = sum(1 for kw in KEYWORDS_EXCLUSION if kw in corpus)
    if nb_exclusions >= 2:
        return 0

    # ─── 3. Inclusions obligatoires (groupe A sport + groupe B métier) ───
    if not any(kw in corpus for kw in KEYWORDS_SPORT):
        return 0
    if not any(kw in corpus for kw in KEYWORDS_METIER):
        return 0

    # ─── 4. Score de base + poids par mot-clé ────────────────────────────
    score = 30
    for kw, poids in SCORE_WEIGHTS.items():
        if kw in corpus:
            score += poids

    # ─── 5. Bonus CPV prestations intellectuelles ────────────────────────
    cpvs = item.get("cpvs", [])
    for cpv, bonus in CPV_BONUS.items():
        if cpv in cpvs:
            score += bonus
            break  # un seul bonus CPV max

    # ─── 6. Surpondération SOURCE de référence (BOAMP/TED/Solideo...) ────
    # Bonus appliqué selon le source_id ; les sources marché public formelles
    # remontent en haut de file pour ne pas être noyées par les signaux faibles.
    src_bonus = SOURCE_WEIGHT_BONUS.get(src_id, 0)
    if src_bonus == 0:
        # Préfixes (ex: boamp_api_xxx)
        for prefix, bonus in SOURCE_WEIGHT_BONUS.items():
            if prefix.endswith("_") and src_id.startswith(prefix):
                src_bonus = bonus
                break
    score += src_bonus

    # ─── 7. Bonus acheteur public prioritaire (ANS/Solideo/Paris 2024…) ──
    score += bonus_acheteur_etat(item)

    # ─── 8. v6 — Pondération par catégorie (cat.1 >> cat.2 > cat.3) ──────
    cat = item.get("_category") or categorize(item)
    if cat == 1:
        score = int(score * 1.5)   # marchés réels : sur-pondération massive
    elif cat == 2:
        score = int(score * 1.0)   # signaux contrats : neutre
    elif cat == 3:
        score = int(score * 0.55)  # veille : pénalité (bruit de fond)
    else:
        return 0

    # ─── 9. v6 — Pénalité si source scrap imprécise (pas domaine officiel) ─
    moteur = item.get("moteur")
    if moteur in ("google", "linkedin"):
        score += 3
        lien = (item.get("lien","") or "").lower()
        if not any(d in lien for d in WHITELIST_DOMAINES_SCRAP):
            score -= 5  # post LinkedIn perso avec mention org -> score bas

    return max(0, min(score, 100))

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

def _favicon_url(lien):
    """Favicon via Google S2 (cache global, toujours disponible)."""
    if not lien:
        return ""
    try:
        from urllib.parse import urlparse
        host = urlparse(lien).netloc
        if host:
            return f"https://www.google.com/s2/favicons?sz=64&domain={host}"
    except Exception:
        pass
    return ""


def formater_opportunite(item, score):
    moteur = item.get("moteur","rss")
    label  = item.get("source_label","")
    lien   = item.get("lien","")
    cat    = item.get("_category") or categorize(item) or 3
    return {
        "id":              generer_id(item),
        "title":           item.get("title",""),
        "source":          item.get("type_source","marche-public"),
        "sourceLabel":     label,
        "moteur":          moteur,
        "category":        cat,                # v6 : 1=marche, 2=signal, 3=veille
        "faviconUrl":      _favicon_url(lien), # v6 : affichage carte
        "types":           deduire_types(item),
        "secteur":         "Sport",
        "emetteur":        label,
        "typeEmetteur":    "Detection automatique",
        "description":     item.get("description","")[:500],
        "datePublication": str(item.get("date_publication", datetime.now().strftime("%Y-%m-%d")))[:10],
        "dateLimite":      None,
        "budget":          "A determiner",
        "contact":         "",
        "lien":            lien,
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
    # v6 — meta.json pour l'affichage version + date MAJ
    meta_file = DATA_FILE.parent / "meta.json"
    now = datetime.now()
    meta = {
        "updated_at_iso":   now.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated_at_human": now.strftime("%d/%m/%y à %Hh%M"),
        "system_version":   os.environ.get("SYSTEM_VERSION", "v6"),
        "count_total":      len(opps),
        "count_cat1":       sum(1 for o in opps if o.get("category") == 1),
        "count_cat2":       sum(1 for o in opps if o.get("category") == 2),
        "count_cat3":       sum(1 for o in opps if o.get("category") == 3),
    }
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log.info(f"Meta sauvegardee -> {meta_file} (version={meta['system_version']}, cat1/2/3={meta['count_cat1']}/{meta['count_cat2']}/{meta['count_cat3']})")

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
        # v6 — catégoriser AVANT le scoring
        item["_category"] = categorize(item)
        if item["_category"] is None:
            continue  # drop : hors périmètre
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
    log.info("Sideline Veille v6 -- Demarrage")
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
        # Moteur 1b : API BOAMP OpenDataSoft (sans clé, filtre services)
        items_rss.extend(lancer_boamp_api())
        log.info(f"[RSS/HTML+BOAMP_API] {len(items_rss)} items bruts")
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
    ap = argparse.ArgumentParser(description="Sideline Veille v6")
    ap.add_argument("--test", action="store_true", help="Sans envoi email")
    ap.add_argument("--only", choices=["rss","google","linkedin"], help="Un seul moteur")
    args = ap.parse_args()
    lancer_veille(test_mode=args.test, only=args.only)
