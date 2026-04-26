# CLAUDE.md — Contexte projet pour Claude Code

Ce fichier est auto-chargé par Claude Code (CLI) à chaque session ouverte dans ce repo.

Le projet **`sideline-veille`** est un scraper Python + page web statique de veille des marchés publics et opportunités sport business pour le cabinet Sideline Conseil (affaires publiques sport).

---

## Lecture obligatoire avant d'intervenir

1. **`HANDOFF.md`** — note de transmission opérationnelle : état actuel, décisions clés (10 points), TODO, pièges connus (12 gotchas), historique chronologique des sessions.
2. **`CAHIER_DES_CHARGES.md`** — spec fonctionnelle complète (architecture, modèle de données, scoring, filtres, CI/CD, checklist de reproduction).

Ces deux fichiers sont la source de vérité. Si tu modifies le système, **mets-les à jour à la fin de la session** (au minimum la section Historique de HANDOFF.md).

---

## Stack technique

- **Backend** : Python 3.11, `feedparser`, `requests`, `beautifulsoup4`, `lxml` (cf. `requirements.txt`)
- **Frontend** : `index.html` autonome (HTML+CSS+JS vanilla, pas de build chain)
- **Données** : JSON dans `data/` (`opportunites.json`, `meta.json`, `seen_ids.json`)
- **CI/CD** : `.github/workflows/sideline.yml` — GitHub Actions cron 11h UTC + push trigger sur code (pas data)
- **Hosting** : GitHub Pages depuis `main`
- **Quotas** : tout est gratuit (BOAMP API, TED RSS, France Marchés RSS, SerpAPI 100/mois, Brevo SMTP 300/jour)

---

## Conventions de travail établies

### Git workflow

- **Push direct sur `main`** : pas de PR, pas de branche feature. Cyril a explicitement demandé ce mode (cf. session 25/04/2026).
- **Messages de commit** : style conventionnel `<type>(<scope>): <description>` puis corps détaillé. Types : `feat`, `fix`, `docs`, `chore`, `data`, `ci`.
- **`[skip ci]`** dans les messages de commits sur `data/` (sinon boucle infinie avec le push trigger).
- **Auteur des commits** : `Cyril Mourin <cyrilmourin@gmail.com>` (utiliser `git -c user.email=... -c user.name=...`).

### Versioning

- Le scraper a un numéro de version dans son header docstring : `v6.12` actuellement.
- Le workflow CI calcule à chaque run `SYSTEM_VERSION = "v6.12 · <short-sha-7>"` et l'injecte au scraper qui l'écrit dans `data/meta.json`.
- Bumper la version dans le header du scraper à chaque changement majeur (jamais oublier).

### Catégories (v6.12)

**2 onglets** dans le frontend (cat.2 fusionnée dans cat.3 le 26/04/2026) :
- **cat.1 — Marchés réels** : BOAMP, TED, France Marchés, profils acheteurs, fédérations /consultations
- **cat.3 — Veille sport business** : SBC (3 sous-feeds), Sporsora, Sport Buzz Business, Sport Stratégies, COSMOS, etc.

Le code Python tolère encore `category=2` (rétrocompat items legacy) mais `categorize()` ne le retourne plus.

### Tabou

**Le repo `cyrilmourin/veille-parlementaire-sport` ne doit JAMAIS être touché.** C'est un projet séparé en production. On peut le LIRE en référence (notamment pour le pattern bloc meta header) mais aucune modif.

---

## Comment lancer un run (déclencher le scraper en prod)

Le workflow se déclenche automatiquement sur :
- cron quotidien 11h UTC
- push sur `main` modifiant `scraper.py`, `.github/workflows/sideline.yml`, `index.html` ou `requirements.txt`
- workflow_dispatch manuel (onglet Actions sur GitHub)

**Pour relancer après une modif scraper** : commit + push, le workflow se déclenche tout seul (~30s pour démarrer, ~1m pour finir).

**Sans modif code** : faire un commit-trigger trivial (ajouter une ligne de commentaire en tête du scraper).

---

## Vérifier les logs Actions

Si tu n'as pas accès direct à `api.github.com` (typique en sandbox) :
- **Claude Code en local** : `gh run list --workflow sideline.yml` puis `gh run view <id> --log`
- **Cowork (sandbox)** : passer par Chrome MCP — naviguer vers `https://github.com/cyrilmourin/sideline-veille/actions`, cliquer le run, expand step "Lancer le scraper", icône engrenage → "View raw logs" (ouvre un nouveau tab Azure blob, parsable via `get_page_text`).

---

## Tester le scraper en local

```bash
# Cloner le repo
git clone https://github.com/cyrilmourin/sideline-veille.git
cd sideline-veille

# Installer dépendances
pip install -r requirements.txt

# Lancer en mode test (n'envoie pas l'e-mail)
python scraper.py --test

# Ou lancer un moteur unique
python scraper.py --only rss      # RSS+HTML+BOAMP API seulement
python scraper.py --only google   # SerpAPI Google
python scraper.py --only linkedin # SerpAPI LinkedIn
```

---

## Tester un changement de scoring sans push

```python
import sys, os
sys.path.insert(0, '.')
for k in ('GMAIL_USER','GMAIL_PASSWORD','GMAIL_DESTINATAIRE','SERPAPI_KEY'):
    os.environ.setdefault(k, '')
import scraper as s

# Test categorize + scorer sur un item synthétique
t = {
    'source_id': 'sportbusiness_club_institutions',
    'source_label': 'SBC',
    'type_source': 'prive',
    'moteur': 'rss',
    'title': 'Federation choisit son agence pour ses affaires publiques',
    'description': 'Mission conseil strategique communication',
    'lien': 'https://www.sportbusiness.club/article-test'
}
t['_category'] = s.categorize(t)
print(f"cat={t['_category']} score={s.scorer(t)}")
```

---

## Structure des sources (`SOURCES` dans scraper.py)

Liste de dicts avec champs : `id`, `label`, `type` (marche-public/federation/prive), `url`, `parser` (rss/html), pour HTML : `selector`/`title_sel`/`desc_sel`/`link_sel`/`timeout`.

**Avant d'ajouter une source** :
1. Vérifier `source_id` unique (collision = bonus de score dupliqué)
2. Pour HTML : tester les sélecteurs CSS dans dev tools navigateur
3. Vérifier que la source ne bloque pas les datacenters GitHub Actions (certains sites renvoient 403 vers AWS/Azure IP)
4. Ajouter dans `SOURCE_CATEGORY` si veille business (cat.3) ; sinon fallback sur `type_source`
5. Optionnel : ajouter dans `SOURCE_WEIGHT_BONUS` un bonus de score pour les sources premium

---

## Constantes principales (à tuner pour ajuster la veille)

| Constante | Rôle |
|---|---|
| `KEYWORDS_SPORT` | Mots du thème sport, requis pour cat.1/2 |
| `KEYWORDS_METIER` | Mots du métier (AP/conseil/com), requis pour cat.1 |
| `KEYWORDS_EXCLUSION` | Drop si ≥2 hits, génériques |
| `KEYWORDS_EXCLUSION_FM_STRICT` | Drop si 1 hit, marchés publics seulement |
| `KEYWORDS_INCLUSION_FM_STRICT` | Inclusion sport/olympique obligatoire pour FM strict |
| `KEYWORDS_SIGNAUX_CONTRATS` | Verbes conjugués "X a confié à Y", "remporte AO" |
| `KEYWORDS_EXCLUSION_NOMINATIONS` | Nominations RH à drop |
| `KEYWORDS_PAGE_STATIQUE` | Pages "présentation/rapport/tribune" à drop (bypass cat.3) |
| `KEYWORDS_EMPLOI` | Offres d'emploi à drop (light pour cat.3) |
| `KEYWORDS_AO_CLOTURE` | Marchés clos à drop (bypass cat.3) |
| `METIER_SIDELINE_BONUS` | +8 à +22pts par mot-clé cœur métier (cap 3 hits) |
| `ACTU_PURE_PENALTY` | −25pts par hit résultats/billetterie/finales (max −50) |
| `WHITELIST_EMETTEURS_LOCAUX_FR` | 103 acteurs institutionnels (régions, métropoles, ministères, fédés) |
| `WHITELIST_ORGS_INSTITUTIONNELLES` | Idem + internationales (CIO, UEFA, FIFA, UCI...) |
| `WHITELIST_DOMAINES_SCRAP` | Domaines acceptés pour scraps Google/LinkedIn |
| `DOMAIN_BLACKLIST` | ~30 domaines à drop (annuaires, jobs, fiches entreprise) |
| `URL_PATH_BLACKLIST` | ~30 patterns URL à drop |
| `CPV_BONUS` | Bonus CPV prestations intellectuelles (79400, 73200...) |
| `CPV_BLACKLIST` | CPV à drop (animation enfants, restauration, transport) |
| `SOURCE_WEIGHT_BONUS` | +12 à +30pts selon source (Marches2030 +30, BOAMP +25...) |
| `ACHETEURS_PRIORITAIRES` | Bonus si ANS/Solideo/Paris 2024/COJOP/CNOSF mentionné |
| `SOURCE_CATEGORY` | Mapping source_id → catégorie (1, 2, 3) |
| `GOOGLE_QUERIES`, `LINKEDIN_QUERIES` | Requêtes SerpAPI consolidées (4 total) |
| `SOURCES` | Liste des 50+ sources RSS/HTML |

---

## Fonctions clés (`scraper.py`)

- `pre_filter(item)` → bool : 10 vérifications (URL/domaine/extension/keywords) avant tout
- `categorize(item)` → 1, 3 ou None : applique pre_filter + détermine catégorie
- `is_institutional_result(item)` → bool : pour scraps Google/LinkedIn, vérifie domaine whitelist OU mention org
- `detect_signal_contrat(item)` → bool : détecte "X a confié à Y", "remporte AO" etc.
- `matches_nomination(item)` → bool : détecte "nommé directeur commercial" etc.
- `match_francemarches_strict(item)` → bool : pour marchés, exige inclusion sport + 0 exclusion stricte
- `bonus_acheteur_etat(item)` → int : bonus 12-25pts si acheteur prioritaire
- `scorer(item)` → 0-100 : 11 étapes de calcul, intègre METIER_BONUS + ACTU_PENALTY + pondération catégorie
- `nettoyer(text)` → str : NFD + apostrophes Unicode + ligatures, lowercase
- `_parse_date(date_str)` → datetime : parse ISO court, RFC 2822 (RSS), ISO complet
- `_favicon_url(lien)` → str : URL Google S2 favicon
- `formater_opportunite(item, score)` → dict : sérialise pour JSON final
- `generer_id(item)` → str : hash MD5 12 chars de l'URL canonique normalisée (fallback titre+source_id)
- `traiter_items(items, vus)` → list : pipe complet categorize → scorer → format
- `lancer_veille(test_mode, only)` → liste opps : orchestrateur principal
- `sauvegarder_donnees(opps)` → écrit `opportunites.json` + `meta.json`

---

## Ce que Claude Code peut faire de plus que Cowork

- **`gh` CLI** : créer/lister/merger des PRs, voir les logs Actions, sans passer par le navigateur
- **Tests locaux complets** : pas de proxy bloquant, peut fetcher n'importe quel RSS pour vérifier les URLs
- **Git interactif** : rebase, cherry-pick, bisect pour identifier régressions
- **Édition multi-fichiers atomique** : modifier scraper.py + index.html + workflow + tests dans un seul commit cohérent

---

## Ce que Cowork avait fait différemment (pour info)

- Push direct sur `main` (pas de PR) — Cyril préfère ce mode rapide, à conserver
- Sandbox bloque les domaines hors infra dev → tests RSS impossibles, on attendait les logs Actions
- API GitHub bloquée → utilisé Chrome MCP pour récupérer les logs raw via UI
- Token PAT GitHub `ghp_AVGhVg…` configuré dans l'URL du remote du dossier Drive Cyril (à révoquer si pas déjà fait)

---

## Checklist fin de session

À faire systématiquement avant de clôturer :

1. Si modif fonctionnelle → bumper version dans header `scraper.py` (v6.12 → v6.13)
2. Push toutes les modifs sur `main`
3. Si modif a déclenché un run, vérifier qu'il est vert
4. Mettre à jour `HANDOFF.md` :
   - État actuel (si version a changé)
   - Décisions clés (si nouveau choix architectural)
   - TODO (cocher les complétés, ajouter les nouveaux)
   - Pièges (si nouveau gotcha découvert)
   - **Toujours** : ajouter une nouvelle entrée datée en haut de Historique
5. Si refonte majeure → mettre à jour `CAHIER_DES_CHARGES.md`
6. Commit final `docs(handoff): MAJ pour vX.Y - <résumé>`
