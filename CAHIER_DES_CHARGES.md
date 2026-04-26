# Cahier des charges — Système de veille marchés/opportunités

Document de spécification fonctionnelle et technique permettant de **reproduire** le système `sideline-veille` (https://github.com/cyrilmourin/sideline-veille) sur un autre thème métier (immobilier, juridique, tech, santé, etc.).

Le projet de référence concerne la veille des marchés et opportunités pour Sideline Conseil (cabinet conseil en affaires publiques sport). Cette doc explique pourquoi chaque brique existe, comment elle marche, et ce qu'il faut changer pour l'adapter.

---

## 1. Vision et objectif

### 1.1 Problème à résoudre

Un cabinet de conseil/agence/consultant indépendant doit suivre :
- les **appels d'offres publics** publiés sur des canaux dispersés (BOAMP, TED, profils acheteurs, sites de fédérations professionnelles…)
- les **signaux de marché** publiés par les médias sectoriels (annonces de partenariats, contrats gagnés par des concurrents, mouvements internes)

Faire cette veille à la main consomme 2-5h par semaine. Les outils SaaS existants (FranceMarchés, MarketIP, Doublet) coûtent 500-3000€/an et ne fusionnent pas marchés + veille business.

### 1.2 Solution livrée

Un site web statique (GitHub Pages) **gratuit**, alimenté par un scraper Python qui tourne quotidiennement via GitHub Actions, qui agrège deux flux :
- **Marchés réels** : appels d'offres publics formels (cœur du sujet)
- **Veille sport business** : actualités sectorielles qualifiées (signaux faibles, contrats annoncés, mouvements de marché)

Un e-mail quotidien (ou hebdomadaire) résume les nouvelles entrées. Une page web filtrable par catégorie/score/source permet l'exploration. Le scoring sur-pondère les opportunités au cœur du métier de l'utilisateur.

### 1.3 Coût total

| Service | Quota gratuit | Coût payant |
|---|---|---|
| GitHub Actions | Illimité (repo public) | — |
| GitHub Pages | Illimité | — |
| BOAMP API (data.gouv) | Sans clé, sans quota | — |
| TED RSS (Europe) | Sans clé | — |
| France Marchés RSS | Sans clé | — |
| SerpAPI (Google/LinkedIn) | 100 req/mois | $50/mois si dépassé |
| Brevo SMTP (e-mail) | 300 mails/jour | — |
| Anthropic API (analyse IA optionnelle) | clé utilisateur | facturation à l'usage |

**Total : 0 €/mois en config standard.**

---

## 2. Architecture technique

### 2.1 Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                    GitHub repo (public)                          │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   scraper.py    │  │ index.html   │  │ data/            │  │
│  │  (Python 3.11)  │  │  (statique)  │  │  - opportunites  │  │
│  └────────┬────────┘  └──────┬───────┘  │  - meta.json     │  │
│           │                  │           │  - seen_ids      │  │
│           │                  │           └──────────────────┘  │
└───────────┼──────────────────┼─────────────────────────────────┘
            │                  │
            │                  │ servi par GitHub Pages
            │                  ▼
            │          https://<user>.github.io/<repo>/
            │
            ▼
   ┌──────────────────────────────────────────┐
   │  GitHub Actions (cron 11h UTC quotidien) │
   │  1. Checkout repo                         │
   │  2. pip install requirements              │
   │  3. python scraper.py                     │
   │  4. git commit data/ → push                │
   └──────────┬───────────────────────────────┘
              │
              ▼
   ┌──────────────────────────────────────────┐
   │  Sources externes (50+ feeds)            │
   │  - RSS (BOAMP, TED, France Marchés...)   │
   │  - HTML scrap (fédérations, médias)      │
   │  - SerpAPI (Google/LinkedIn)             │
   │  - BOAMP OpenDataSoft API                │
   └──────────────────────────────────────────┘
```

### 2.2 Stack technique

- **Backend scraping** : Python 3.11, `feedparser`, `requests`, `beautifulsoup4`, `lxml`
- **Frontend** : HTML/CSS/JS vanilla (pas de build, pas de framework)
- **Données** : JSON statique (`data/opportunites.json`, `data/meta.json`, `data/seen_ids.json`)
- **CI/CD** : GitHub Actions (workflow YAML)
- **E-mail** : Brevo (ex-Sendinblue) SMTP
- **Hosting** : GitHub Pages (servi depuis `main`)

### 2.3 Pourquoi ces choix

- **Python pour le scraper** : `feedparser` est la lib de référence pour RSS/Atom, BS4 pour HTML, requests bien rodé
- **JSON statique au lieu d'une DB** : pas de serveur à maintenir, le repo git est la base, l'historique git fait le rollback
- **Pas de framework JS** : un fichier HTML auto-suffisant, pas de build chain, fonctionne en ouvrant le fichier en local
- **GitHub Pages public** : illimité gratuit, HTTPS auto, déploiement à chaque push

---

## 3. Modèle de données

### 3.1 `data/opportunites.json`

Tableau d'objets `Opportunite`. Schéma cible :

```json
{
  "id": "abc123def456",            // hash MD5 de l'URL canonique
  "title": "Marché conseil stratégique fédération XYZ",
  "source": "marche-public",       // type d'origine
  "sourceLabel": "BOAMP — CPV 794",
  "moteur": "rss",                 // rss / html / google / linkedin / boamp_api
  "category": 1,                   // 1 = marchés / 3 = veille business
  "faviconUrl": "https://www.google.com/s2/favicons?sz=64&domain=boamp.fr",
  "types": ["affaires-publiques", "strategie"],
  "secteur": "Sport",              // libellé thématique
  "emetteur": "Fédération XYZ",
  "typeEmetteur": "Fédération sportive nationale",
  "description": "Texte court (max 500 chars)",
  "datePublication": "2026-04-25", // ISO YYYY-MM-DD
  "dateLimite": "2026-05-25",      // ISO ou null
  "budget": "50 000 - 100 000 €",
  "contact": "marches@xyz.fr",
  "lien": "https://www.boamp.fr/avis/...",
  "nouvelle": true,                // true pendant 48h après détection
  "urgent": false,                 // true si dateLimite < 15j
  "score": 87,                     // 0-100, calculé par scorer()
  "angles": ["Mission au cœur du métier", ...], // analyses optionnelles
  "source_auto": true              // vs items démo
}
```

### 3.2 `data/meta.json`

Métadonnées du dernier run, lues par le frontend pour afficher la version + date MAJ.

```json
{
  "updated_at_iso": "2026-04-26T13:00:00",
  "updated_at_human": "26/04/26 à 13h00",
  "system_version": "v6 · abc1234",  // injecté par CI : v6·<short-sha-7> (format figé v6 par convention, pas la version mineure du scraper)
  "count_total": 200,
  "count_cat1": 45,
  "count_cat2": 0,                       // gardé pour rétrocompat
  "count_cat3": 155
}
```

### 3.3 `data/seen_ids.json`

Tableau des `id` déjà processés. Permet la déduplication entre runs : un item dont l'id est déjà connu est ignoré dans les nouvelles runs.

```json
["abc123def456", "789xyz...", ...]
```

---

## 4. Pipeline de scraping

### 4.1 Architecture en couches

Le scraper a **4 couches de sources** (voir `SOURCES` dans `scraper.py`) :

1. **Couche 1 — Marchés publics officiels** : BOAMP (par CPV), TED/JOUE (Europe), France Marchés (avec requêtes thématiques personnalisées), CNOSF, Maximilien IDF, profils acheteurs spécifiques (Marches2030 = COJOP+SOLIDEO).
2. **Couche 2 — Fédérations sectorielles** : pages `/consultations` ou `/appels-offres` des fédérations sportives (FFR, FFF, FFBB, FFHandball, FFVolley, FFN, FFT, FFJudo, FFR XIII, FFA, FFHandisport, FFVoile, FFBad, FFME, FFE).
3. **Couche 3 — Médias sectoriels** : SportBusiness Club (3 sous-feeds : institutions publiques, agences, brèves), SPORSORA (marketing + actualités), Sport Buzz Business, Sport Stratégies, COSMOS (cosmos-sports.fr), GIE Sport Expertise, Café du Sport Biz, L'Équipe sport business, News Tank Sport.
4. **Couche 4 — Acteurs internationaux** : feeds activés/désactivés selon disponibilité (CIO, FIFA, UEFA, ANS bloqués depuis GitHub Actions, contournés par SerpAPI).

### 4.2 Trois moteurs de détection

| Moteur | Fonction | Avantage | Limite |
|---|---|---|---|
| **RSS / HTML** (`parse_rss`, `parse_html`) | Lecture directe des flux | Rapide, gratuit, robuste | Dépend de la stabilité des URLs et sélecteurs CSS |
| **SerpAPI (Google)** (`recherche_serpapi`) | Recherches Google ciblées | Capture les sources pas en RSS, pages dynamiques | Quota 100 req/mois ; activé lundi-vendredi seulement |
| **SerpAPI (LinkedIn)** | Recherches `site:linkedin.com` | Capture posts entreprise/posts | Quota partagé avec Google |
| **BOAMP API OpenDataSoft** (`lancer_boamp_api`) | API officielle data.gouv | Pas de quota, données structurées CPV/dates | Spécifique BOAMP français |

### 4.3 Ordre d'exécution

```
lancer_veille()
  ├─ charger_vus()                       # seen_ids.json
  ├─ charger_donnees()                   # opportunites.json (cutoff 90j applique)
  ├─ Si moteur RSS actif :
  │    ├─ parse_rss() pour chaque source RSS
  │    ├─ parse_html() pour chaque source HTML
  │    └─ lancer_boamp_api()
  ├─ Si moteur Google actif (lun-ven) :
  │    └─ lancer_google()                # 3 requêtes consolidées
  ├─ Si moteur LinkedIn actif (lun-ven) :
  │    └─ lancer_linkedin()              # 1 requête consolidée
  ├─ traiter_items() pour chaque batch :
  │    ├─ categorize() → cat 1 / 3 / None
  │    ├─ generer_id() → hash(URL canonique) ou hash(titre+source_id)
  │    ├─ Skip si id ∈ seen_ids
  │    ├─ scorer() → score 0-100
  │    ├─ Skip si score < seuil (cat.1 ≥ 20, cat.3 ≥ 12)
  │    └─ formater_opportunite()
  ├─ Dédup multi-source (titre+emetteur) → garde meilleur score
  ├─ Tri par score descendant, top 200
  ├─ sauvegarder_donnees()              # opportunites.json + meta.json
  ├─ sauvegarder_vus()                   # seen_ids.json mis à jour
  └─ envoyer_email() si nouvelles_opps non vide et pas mode test
```

---

## 5. Système de filtrage

Trois filtres en cascade, appliqués pour CHAQUE item collecté :

### 5.1 Pré-filtre (`pre_filter`) — drop radical

S'applique en tout premier. Drop l'item si :

1. **Domaine blacklisté** (`DOMAIN_BLACKLIST`) : ~30 domaines exclus en bloc — annuaires juridiques (alexia.fr, village-justice), job boards (indeed, apec, pole-emploi, welcometothejungle), annuaires entreprises (pappers, societe.com, manageo, infogreffe, kompass, bodacc), e-commerce (amazon, fnac, decathlon).
2. **Pattern URL blacklisté** (`URL_PATH_BLACKLIST`) : `linkedin.com/in/` (profils perso), `linkedin.com/jobs/`, `/learning/`, `/presentation-de`, `/qui-sommes-nous`, `/rapports-de-`, `/dossier-de-presse`, `/communique-de-presse`, `/discours-`, `/biographie`, `/annonce/`, `/offre-emploi`, `/recrutement`, `/fiche/`, `/questions/`, `/forum/`, `wikipedia.org/wiki/`, `/boutique`, `/panier`.
3. **Extensions de fichier suspectes** (`SUSPECT_EXTENSIONS = .pdf .doc .docx .ppt .pptx`) : drop sauf si l'URL ou le titre contient un signal AO explicite (`marche`, `consultation`, `appel-offre`, `dce`, `cahier-des-charges`).
4. **Mots-clés page statique** (`KEYWORDS_PAGE_STATIQUE`) : "présentation de", "rapports de", "dossier de presse", "biographie", "interview de", "tribune de", "mentions légales". **Bypass pour cat.3 mappée** (sur SBC/Sporsora ces mots SONT du contenu légitime).
5. **Mots-clés emploi** (`KEYWORDS_EMPLOI`) : "offre d'emploi", "recrutement", "CDI/CDD/stage/freelance", "h/f", "(h/f)", "intitulé du poste", "salaire mensuel", "business development", "sales manager", "key account". **Pour cat.3 mappée**, version stricte sans "business development"/"sales manager" (qui sont des termes business légitimes).
6. **AO clôturé** (`KEYWORDS_AO_CLOTURE`) : "appel d'offre clôturé", "consultation clôturée", "marché attribué le", "date limite dépassée". **Bypass pour cat.3 mappée**.
7. **Date limite passée** : si `dateLimite` < aujourd'hui → drop. **Bypass pour cat.3 mappée**.
8. **CPV blacklist** (`CPV_BLACKLIST`) : 92331210 (animation enfants), 55520000 (restauration coll), 60100000 (transport), 75300000 (sécurité sociale), 79600000 (recrutement), 80500000 (formation).
9. **LinkedIn restreint** : seules les URLs `/posts/`, `/pulse/`, `/feed/update/`, `/company/<slug>/posts/`, `/company/<slug>/feed/`, `/showcase/` sont acceptées. Tout le reste (`/in/`, `/jobs/`, `/company/<slug>/` racine, `/about`, `/people`, `/life`) est droppé.
10. **Filtre titre fédération** : pour les sources `type=federation`, le titre doit contenir un mot AO/consultation/marché/candidature/avis. Sinon drop (filtre les actualités sportives qui passaient les sélecteurs CSS larges).

### 5.2 Filtre FranceMarchés strict (`match_francemarches_strict`)

S'applique aux items `type=marche-public` ou `source_id` commençant par `boamp_`/`ted_`/`francemarches_`/`marches2030`/`cnosf_`/`maximilien_` :
- **Inclusion obligatoire** : au moins un mot dans `KEYWORDS_INCLUSION_FM_STRICT` (sport, sportif, sportifs, sportive, sportives, olympique, olympiques)
- **Exclusion stricte** : aucun mot dans `KEYWORDS_EXCLUSION_FM_STRICT` (26 termes : transport scolaire, périodiques, location, assurance, conformité, surveillance, nettoyage, exploitation, gestion/exploitation, maintenance, entretien, organisation d'activités, maîtrise d'œuvre, BAFA, BAFD, restauration collective, hébergement, titres de restauration). Un seul match suffit à drop.

### 5.3 Filtre institutionnel (`is_institutional_result`)

S'applique aux items `moteur=google` ou `moteur=linkedin` (scraps Google/LinkedIn). L'item est accepté si :
- son URL contient un domaine de `WHITELIST_DOMAINES_SCRAP` (boamp.fr, sports.gouv.fr, ffr.fr, marches2030.org, linkedin.com/company/, etc.) **OU**
- son titre/description mentionne une organisation de `WHITELIST_ORGS_INSTITUTIONNELLES` (UCI, CIO, FFR, COJOP 2030, ministère des Sports, ANS, CNOSF, etc.)

Sinon drop (post LinkedIn perso sans rattachement à une org reconnue).

### 5.4 Whitelist émetteurs locaux

Pour les marchés cat.1, une `WHITELIST_EMETTEURS_LOCAUX_FR` de 103 acteurs (13 régions, 10 métropoles, ministères, ANS, CNOSF, fédés, ligues, organisateurs grands événements UCI 2027/Mondial Basket 2031/Euro 2028/COJOP 2030) sert à scorer. Un marché de petite ville inconnue n'est pas droppé mais score plus bas.

---

## 6. Système de scoring

### 6.1 Calcul du score (`scorer`)

Score initial = 30. Puis on applique en séquence :

1. **Filtre FM strict** (cat.1) : si match → score=0 (drop).
2. **Filtre exclusions générales** : ≥2 mots de `KEYWORDS_EXCLUSION` dans le corpus → score=0.
3. **Filtre inclusion** : KEYWORDS_SPORT obligatoire pour cat.1/2 (bypass cat.3). KEYWORDS_METIER obligatoire pour cat.1.
4. **Bonus mot-clés génériques** (`SCORE_WEIGHTS`) : +10 à +22pts par mot-clé sport/conseil/communication détecté.
5. **Bonus CPV** (`CPV_BONUS`) : +8 à +15pts pour les codes CPV prestations intellectuelles (79400, 79410, 73200, 92600).
6. **Bonus source** (`SOURCE_WEIGHT_BONUS`) : +12 à +30pts selon la source (Marches2030 +30, BOAMP conseil +25, TED sport +25, CNOSF +25, SBC institutions +12).
7. **Bonus acheteur prioritaire** (`bonus_acheteur_etat`) : +12 à +25pts si l'item mentionne ANS/Solideo/Paris 2024/COJOP/ministère/CNOSF.
8. **Bonus métier Sideline** (`METIER_SIDELINE_BONUS`) — v6.11 : +8 à +22pts par mot-clé (cap 3) :
   - Affaires publiques (+22), influence (+18), lobbying (+18), plaidoyer (+16)
   - Conseil stratégique (+18), stratégie d'influence (+20)
   - Communication institutionnelle (+14), RP (+12), relations presse (+12)
   - Sponsoring (+12), mécénat (+12), partenariat stratégique (+12)
   - Droit du sport (+15), gouvernance (+12), schéma directeur (+10)
   - Marketing sportif (+10), agence (+8), prestataire (+8)
   - Signaux contrats : remporte/attribue/choisi par/renouvelle son partenariat (+10 à +14)
9. **Pénalité actu pure** (`ACTU_PURE_PENALTY`) — v6.11 : −25pts par hit (max −50) si le contenu contient résultats/finales/billetterie/transferts/calendrier/podium/blessures. Si pas de mot métier ET actu pure → −10 supplémentaire.
10. **Pondération par catégorie** :
    - Cat.1 : score × **1.5** (sur-pondération marchés réels)
    - Cat.3 : score × **0.85** (léger malus veille)
11. **Pénalité scrap imprécise** : si moteur Google/LinkedIn et URL hors domaine officiel → −5pts.

Score final clampé `[0, 100]`.

### 6.2 Seuils d'inclusion

- **Cat.1** : score ≥ 20 pour être conservé
- **Cat.3** : score ≥ 12 (seuil plus bas pour ne pas perdre les articles courts)

---

## 7. Frontend (`index.html`)

### 7.1 Composants

- **Header** : logo + bloc meta à droite ("Données M.A.J 26/04/26 à 13h00 · Version v6 · abc1234")
- **Page-title** : titre éditorial + barre de recherche + bouton "Actualiser"
- **Nav onglets** (2 onglets v6.12) : Marchés (cat.1) + Veille sport business (cat.3, ex-cat.2 fusionnée)
- **Stats row** : 4 cards calculées **toujours sur cat.1** quel que soit l'onglet actif (Opportunités actives, Nouvelles 48h, Échéance <15j, Score moyen)
- **Filtres** : type (AP/Stratégie/Com/Influence) + tri (score/date/titre)
- **Cards opportunités** : favicon XL 56px à gauche, titre + score à droite, tags (types, secteur, urgent), description, footer avec sourceLabel + dates
- **Sidebar** : sources actives, mots-clés alertes (toggle), assistant IA (Anthropic API optionnelle)
- **Modal détail** : full info + analyse IA + lien externe

### 7.2 Logique JavaScript

- `chargerDonnees()` : fetch `data/opportunites.json` et `data/meta.json`, peuple `TOUTES_OPPS` et le bloc meta
- `setTab(n)` : change l'onglet actif, déclenche `filterOpps()`
- `filterOpps()` : filtre `TOUTES_OPPS` par catégorie + recherche + filtres, met à jour les compteurs onglets, trie, appelle `renderOpps()`
- `renderStats()` : calcule TOUJOURS sur cat.1 (4 cards stats indépendantes de l'onglet)
- `localStorage` : tracking des items vus (passe `nouvelle=false` après ouverture du modal), config alertes, clé API Anthropic

---

## 8. CI/CD GitHub Actions

### 8.1 Workflow `.github/workflows/sideline.yml`

```yaml
on:
  schedule:
    - cron: '0 11 * * *'        # quotidien 11h UTC = 13h Paris
  push:
    branches: [main]
    paths:                       # relance auto après modif code
      - 'scraper.py'
      - '.github/workflows/sideline.yml'
      - 'index.html'
      - 'requirements.txt'
  workflow_dispatch:             # trigger manuel UI
```

### 8.2 Steps

1. Checkout v4
2. Setup Python 3.11 + cache pip
3. `pip install -r requirements.txt`
4. `mkdir -p data logs`
5. **Calculer SYSTEM_VERSION** : `SHORT_SHA=$(git rev-parse --short=7 HEAD); echo "system_version=v6 · $SHORT_SHA" >> $GITHUB_OUTPUT`
6. **Lancer le scraper** : passe la version env, mode lundi-vendredi (RSS+SerpAPI+LinkedIn) sinon week-end (RSS-only pour préserver quota SerpAPI)
7. **Sauvegarder data** : `git add data/opportunites.json data/seen_ids.json data/meta.json; git commit -m "data: ... [skip ci]"; git push`
8. **Archiver logs** : upload-artifact 7 jours

### 8.3 Pourquoi `[skip ci]`

Sans `[skip ci]`, chaque commit data déclencherait un nouveau workflow → boucle infinie. La balise indique à GitHub Actions de ne pas relancer.

### 8.4 Secrets requis

- `GMAIL_USER`, `GMAIL_PASSWORD`, `GMAIL_DESTINATAIRE` : creds Brevo (oui malgré le nom, c'est Brevo SMTP)
- `SERPAPI_KEY` : clé SerpAPI (gratuite 100 req/mois)

---

## 9. Quotas et garde-fous

| Quota | Stratégie de respect |
|---|---|
| **GitHub Actions** | Repo public = illimité. Pas de quota à surveiller. |
| **SerpAPI 100/mois** | 4 req/run × 5 jours/sem × 4.35 sem = ~88/mois, marge ~12. Lundi-vendredi seulement, week-end RSS-only. |
| **Brevo SMTP 300/jour** | 1 mail/run × 5 jours = 5/sem max. Largement OK. |
| **BOAMP OpenDataSoft** | Pas de quota officiel, ~10 req/jour. OK. |
| **TED RSS, France Marchés RSS** | Aucun quota. OK. |

---

## 10. Reproduire pour un autre thème — checklist

### 10.1 Phase 1 — Spécification métier (1-2j)

- [ ] **Identifier le métier cible** (ex : conseil immobilier, conseil RH, conseil tech…)
- [ ] **Lister les mots-clés métier** : 15-30 termes qui caractérisent les opportunités au cœur du métier (équivalent `METIER_SIDELINE_BONUS`)
- [ ] **Lister les exclusions métier** : 10-30 termes qui caractérisent l'actu sectorielle pure non pertinente (équivalent `ACTU_PURE_PENALTY`)
- [ ] **Lister les organisations institutionnelles cibles** : ministères, agences publiques, fédérations professionnelles, grandes entreprises (équivalent `WHITELIST_EMETTEURS_LOCAUX_FR` + `WHITELIST_ORGS_INSTITUTIONNELLES`)
- [ ] **Lister les CPV pertinents** (si France) : codes prestations intellectuelles à sur-pondérer (équivalent `CPV_BONUS`) et codes à exclure (équivalent `CPV_BLACKLIST`)

### 10.2 Phase 2 — Sources de données (2-3j)

- [ ] **Identifier les flux marchés publics** :
  - BOAMP par CPV (FR)
  - TED RSS par requête (Europe)
  - France Marchés (avec recherches personnalisées sectorielles)
  - Profils acheteurs PLACE pour grands acheteurs publics
  - Maximilien IDF si sujet francilien
- [ ] **Identifier les associations/fédérations professionnelles** avec page `/consultations` ou `/appels-offres` (ex : pour conseil santé → fédérations hospitalières, syndicats médicaux ; pour conseil tech → BPI, syndicats numérique)
- [ ] **Identifier 5-10 médias sectoriels** avec flux RSS ou pages web scrapables (ex : pour immobilier → Business Immo, Le Moniteur, Construction21 ; pour tech → JDN, Frenchweb, Maddyness)
- [ ] **Tester chaque URL** :
  - RSS : convention WordPress `/feed/` souvent
  - HTML : inspecter avec dev tools pour trouver les bons sélecteurs CSS
  - Vérifier qu'aucune source ne renvoie de 403 depuis GitHub Actions (certains sites bloquent les datacenters)
- [ ] **Définir les requêtes SerpAPI** : 3 requêtes Google + 1 LinkedIn consolidées avec opérateur `OR` pour rester sous 100/mois.

### 10.3 Phase 3 — Adaptation du code (1-2j)

- [ ] **Fork le repo** `cyrilmourin/sideline-veille`
- [ ] **Renommer** : repo, titre HTML, libellés `Sideline` → `<NomMétier>`, `Sport` → `<thème>`
- [ ] **Remplacer dans `scraper.py`** :
  - `KEYWORDS_SPORT` → mots-clés thème (ex: immobilier, batiment, foncier)
  - `KEYWORDS_METIER` → mots-clés métier (ex: conseil immobilier, asset management)
  - `KEYWORDS_EXCLUSION` → exclusions thème (ex: pour immobilier : viager, location courte durée)
  - `KEYWORDS_INCLUSION_FM_STRICT` → inclusions stricte thème
  - `KEYWORDS_EXCLUSION_FM_STRICT` → exclusions strictes thème
  - `KEYWORDS_SIGNAUX_CONTRATS` → verbes conjugués spécifiques au métier
  - `KEYWORDS_PAGE_STATIQUE` → patterns à drop (probablement génériques, garder tel quel)
  - `KEYWORDS_EMPLOI` → patterns emploi (génériques, garder)
  - `KEYWORDS_AO_CLOTURE` → patterns AO clos (génériques, garder)
  - `WHITELIST_EMETTEURS_LOCAUX_FR` → liste acteurs institutionnels du métier
  - `WHITELIST_ORGS_INSTITUTIONNELLES` → idem + acteurs internationaux
  - `WHITELIST_DOMAINES_SCRAP` → domaines officiels du métier
  - `DOMAIN_BLACKLIST` → domaines à drop (génériques, peut-être ajouter quelques job boards spécifiques au secteur)
  - `URL_PATH_BLACKLIST` → patterns URL à drop (génériques, garder)
  - `METIER_SIDELINE_BONUS` → mots-clés cœur de métier avec poids
  - `ACTU_PURE_PENALTY` → patterns actu sectorielle non pertinente
  - `SOURCE_CATEGORY` → mapping source_id → catégorie (1 marchés, 3 veille)
  - `SOURCE_WEIGHT_BONUS` → bonus de score par source
  - `ACHETEURS_PRIORITAIRES` → bonus pour acheteurs publics clés du métier
  - `CPV_BONUS` et `CPV_BLACKLIST` → CPV thème
  - `GOOGLE_QUERIES`, `LINKEDIN_QUERIES` → 4 requêtes SerpAPI consolidées
  - `SOURCES` → liste complète des sources RSS/HTML (50+ entrées)
- [ ] **Adapter `index.html`** :
  - Titre, logo, couleurs (variables CSS `--or` `--noir` etc.)
  - Libellés des onglets ("Marchés" + "Veille <thème> business")
  - Libellés des stats ("Opportunités actives", "Nouvelles 48h"...)
  - Items démo `DEMO_DATA` (pour preview avant 1er run)

### 10.4 Phase 4 — Déploiement (0.5j)

- [ ] **Activer GitHub Pages** : Settings → Pages → main branch
- [ ] **Configurer secrets** : Settings → Secrets → Actions
  - `SERPAPI_KEY` (créer compte sur serpapi.com, plan gratuit)
  - `GMAIL_USER`, `GMAIL_PASSWORD`, `GMAIL_DESTINATAIRE` (créer compte Brevo, créer SMTP key)
- [ ] **Premier run manuel** : onglet Actions → workflow_dispatch → Run
- [ ] **Vérifier les logs** : tous les feeds doivent retourner ≥0 entrées sans timeout. Désactiver les sources qui retournent systématiquement 403/timeout.
- [ ] **Vérifier `data/meta.json`** : doit contenir un `system_version` non-vide.
- [ ] **Vérifier `index.html` en live** : refresh + Cmd+Shift+R, le bloc meta s'affiche, les onglets fonctionnent, les compteurs sont à jour.

### 10.5 Phase 5 — Itération (continue)

- [ ] **Première semaine** : surveiller les e-mails, identifier les items hors-cible et ajuster `KEYWORDS_EXCLUSION` ou `DOMAIN_BLACKLIST`
- [ ] **Troisième semaine** : ajuster les pondérations `METIER_*_BONUS` et `ACTU_PURE_PENALTY` selon les scores observés
- [ ] **Mensuel** : revue des sources qui retournent toujours 0 (à supprimer ou remplacer par scrap HTML)

---

## 11. Pièges connus / leçons apprises

Doc complète dans `HANDOFF.md` section "Pièges connus". Synthèse des plus importants pour la repro :

1. **`os.environ.get(KEY, "default")` retourne `""` si la clé existe mais est vide.** Toujours utiliser `os.environ.get(KEY) or "default"`.

2. **Refactor d'éléments DOM** : penser aux références JS résiduelles. Si tu supprimes un `<span id="X">`, grep le JS pour les `getElementById('X')` qui crashent avec `null.textContent`.

3. **Cache navigateur agressif** sur les fichiers HTML statiques GitHub Pages. Toujours hard refresh (Cmd+Shift+R) après merge UI.

4. **Doublons `source_id`** : vérifier l'unicité quand on ajoute une source. Sinon collisions dans les bonus de score.

5. **La sandbox Cowork bloque les domaines hors infra dev**. On ne peut pas tester les RSS depuis la sandbox (sportbusiness.club, etc.) ; on attend les logs Actions.

6. **Items legacy sans `category`** : prévoir un script de migration `categorize()` rétroactif quand on ajoute des champs au schema.

7. **Cron GitHub Actions peut avoir 2-4h de retard**. Pas un bug, juste un fait du free tier.

8. **Apostrophes Unicode dans les keywords** : la fonction `nettoyer()` strip les accents et apostrophes ; toujours écrire les keywords sans accent ni apostrophe ("a confie sa communication a" pas "a confié sa communication à").

9. **Bug critique RFC 2822** (v6.10) : si `_parse_date` ne sait pas lire le format `Fri, 24 Apr 2026 12:39:24 +0000` que les feeds RSS retournent, les items finissent en `seen_ids` mais disparaissent du JSON par cutoff 90j. Toujours utiliser `email.utils.parsedate_to_datetime` pour les pubDate RSS.

10. **Sélecteurs CSS trop larges** sur les pages /consultations des fédérations : capturent menus, billetterie, dates isolées. Compléter avec un filtre titre obligatoire (`type=federation` doit avoir `consultation`/`appel`/`marché` dans le titre).

11. **Déduplication multi-source** : un même AO peut être publié sur BOAMP RSS + BOAMP API + France Marchés avec 3 URLs différentes. Dédup par URL canonique ne suffit pas → ajouter dédup par `(titre normalisé + émetteur)`.

12. **Le repo `veille-parlementaire-sport` sert de référence d'architecture** (bloc meta header, etc.) mais ne JAMAIS modifier. C'est un projet séparé en production.

---

## 12. Ressources et liens utiles

- **Repo de référence** : https://github.com/cyrilmourin/sideline-veille
- **Documentation BOAMP API** : https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/
- **Documentation TED Europe** : https://ted.europa.eu/TED/misc/disclaimer.do
- **France Marchés** : https://www.francemarches.com/
- **Profils acheteurs PLACE** : https://www.marches-publics.gouv.fr/
- **SerpAPI** : https://serpapi.com/ (compte gratuit 100 req/mois)
- **Brevo SMTP** : https://www.brevo.com/ (300 mails/jour gratuit)
- **GitHub Pages doc** : https://docs.github.com/pages
- **GitHub Actions doc** : https://docs.github.com/actions
- **feedparser doc** : https://feedparser.readthedocs.io/
- **BeautifulSoup doc** : https://www.crummy.com/software/BeautifulSoup/bs4/doc/

---

## 13. Récapitulatif effort de reproduction

Pour un développeur familier avec Python + GitHub Actions :

| Phase | Effort |
|---|---|
| Phase 1 — Spec métier | 1-2 jours |
| Phase 2 — Identification des sources | 2-3 jours |
| Phase 3 — Adaptation du code | 1-2 jours |
| Phase 4 — Déploiement initial | 0.5 jour |
| Phase 5 — Itération (3 premières semaines) | 0.5j/sem soit 1.5j |

**Total : ~7-9 jours de développement** pour avoir un système opérationnel sur un autre thème.

Pour un consultant non-développeur, prévoir 2-3× plus en faisant accompagner par un dev senior ou via un agent IA (Claude Cowork, etc.).

---

*Document généré le 26 avril 2026, version finale v6.12 du système. Maintenu en parallèle de `HANDOFF.md` (note de transmission opérationnelle).*
