# HANDOFF — sideline-veille

Note de transmission pour reprendre la maintenance du projet **Sideline Veille Marchés** (https://github.com/cyrilmourin/sideline-veille).

---

## État actuel

Le projet est en **v6 (refonte 3 catégories)** depuis le 24/04/2026.

**Pipeline de scraping** (`scraper.py`, ~1800 lignes) :
- 3 moteurs de détection : RSS/HTML (51 sources), SerpAPI/Google (3 requêtes consolidées), LinkedIn via SerpAPI (1 requête consolidée), plus l'API BOAMP OpenDataSoft (sans clé).
- Classification automatique en 3 catégories via `categorize(item)` :
  - **Cat.1 — Marchés réels** : appels d'offres publics formels (BOAMP, TED/JOUE, marches2030, profils acheteurs ANS/Solideo/CNOSF, France Marchés). C'est le cœur du sujet.
  - **Cat.2 — Signaux contrats** : annonces "X a confié sa communication à Y", "remporte l'appel d'offre", "renouvelle son partenariat avec…" (35 verbes conjugués précis).
  - **Cat.3 — Veille sport business** : flux RSS qualifiés (SportBusiness Club, Café du Sport Biz, Sporsora, Sport Stratégies, COSMOS, GIE Sport Expertise, L'Équipe, News Tank, Kingcom).
- Filtre institutionnel sur scraps Google/LinkedIn : un post de particulier est droppé sauf s'il vient d'un domaine whitelisté (linkedin.com/company/, sports.gouv.fr, boamp.fr, etc.) OU mentionne une org reconnue (UCI, FFR, COJOP 2030, etc.).
- Filtre nominations RH : drop des "nouveau directeur commercial", "prise de fonction", "nommé(e)", "promu(e)" (20 patterns).
- Whitelist 103 émetteurs locaux FR : 13 régions, 10 métropoles, ministères, agences, fédés/ligues, organisateurs grands événements (UCI 2027, Mondial Basket 2031, Euro 2028, COJOP 2030).
- Scoring pondéré par catégorie : cat.1 × 1.5, cat.2 × 1.0, cat.3 × 0.55, plus −5pts si scrap hors domaine officiel.
- Génération de `data/opportunites.json` (items) et `data/meta.json` (version + date MAJ + compteurs cat.1/2/3) à chaque run.

**Frontend** (`index.html`, page statique servie via GitHub Pages) :
- Header avec bloc meta à droite : "Données M.A.J JJ/MM/AA à HHhMM" + "Version v6 · short-sha".
- Nav à 3 onglets sous le header avec compteur dynamique par onglet (ex : "Marchés 36").
- Chaque carte affiche un favicon du site source (via le service Google S2).
- Stats top-row (opportunités actives, nouvelles, échéances, score moyen) toujours basées sur cat.1, peu importe l'onglet actif.
- Recherche, tri (score/date/titre), filtres type/source.
- Modal détail avec analyse IA (Anthropic) optionnelle si l'utilisateur configure sa clé.

**CI/CD** (`.github/workflows/sideline.yml`) :
- Cron quotidien à 11h UTC (13h Paris).
- Lundi-vendredi : run complet (RSS + SerpAPI + LinkedIn). Week-end : RSS-only (préserve le quota SerpAPI).
- Variable `SYSTEM_VERSION = v6 · <short-sha>` calculée puis injectée dans l'env du scraper.
- Auto-commit `data/opportunites.json + seen_ids.json + meta.json` avec `[skip ci]`.
- Logs archivés 7 jours via upload-artifact.

**Distribution actuelle des items** (snapshot 24/04/2026 après migration v6) :
- 36 items en cat.1 / 0 en cat.2 / 26 en cat.3 / 34 droppés depuis l'ancien JSON (essentiellement posts LinkedIn de particuliers).

---

## Décisions clés

**1. Une seule branche / un seul workflow.**
Lors de l'audit du 19/04/2026, on a supprimé `.github/workflows/veille.yml` (doublon exact de `sideline.yml`) et `sideline.yml` à la racine (jamais exécuté par GitHub Actions). Le repo n'a maintenant qu'un seul point d'entrée CI.
*Pourquoi :* éviter les confusions de "quel workflow tourne vraiment" lors de futures modifs de cron/quotas.

**2. SerpAPI consolidé en 4 requêtes/run, lundi-vendredi.**
8 requêtes Google + 3 LinkedIn → 3 Google (fusion `OR`) + 1 LinkedIn consolidé = 4 req × 22 jours ouvrés = ~88/mois pour 100 gratuits.
*Pourquoi :* le quota gratuit SerpAPI est de 100 recherches/mois. Avec l'ancienne config (11 req × 2j/sem), on était à 94/mois — marge dangereuse. Cyril préfère la consolidation par OR plutôt que de réduire les jours.

**3. Logique FranceMarchés stricte sur les sources marché public.**
`match_francemarches_strict()` exige au moins un mot d'inclusion sport/sportif/olympique ET aucun mot de la liste d'exclusion stricte (transport scolaire, périodiques, location, assurance, conformité, surveillance, nettoyage, exploitation, maintenance, entretien, organisation d'activités, maîtrise d'œuvre, BAFA/BAFD, restauration collective, hébergement, etc. — 26 patterns).
*Pourquoi :* reproduire localement la logique d'alerte FranceMarchés que Cyril utilisait avant, pour ne pas re-payer un abonnement.

**4. Scoring pondéré par catégorie, pas drop-or-keep absolu.**
Plutôt que filtrer "tout sauf cat.1", on garde les 3 catégories mais on applique des coefficients (1.5/1.0/0.55) et la home n'affiche que cat.1 par défaut.
*Pourquoi :* préserve l'historique signaux/veille pour analyse a posteriori, sans polluer la vue marchés.

**5. Whitelist domaines + mention d'org pour scraps Google/LinkedIn.**
Un post LinkedIn de particulier est droppé SAUF s'il mentionne une organisation institutionnelle whitelistée (UCI, fédé, COJOP, ministère, etc.) — règle "mention org = OK, score bas".
*Pourquoi :* évite que tout post personnel ("Jean Dupont — mes réflexions sur le sport") pollue la veille, mais conserve les signaux légitimes (ex : "Appel à concurrence 2026 droit du sport UCI" posté par un consultant indépendant).

**6. `meta.json` séparé du JSON de données.**
`data/opportunites.json` reste un array d'items pur ; `data/meta.json` contient `updated_at_iso`, `updated_at_human`, `system_version`, et les compteurs cat.1/2/3.
*Pourquoi :* inspiré de la structure de `veille-parlementaire-sport`. Évite de casser les consommateurs JSON existants si on ajoute des métadonnées futures.

**7. `SYSTEM_VERSION` calculée dans le workflow CI, pas hardcodée.**
Format `v6 · <short-sha-7chars>` injecté via `git rev-parse --short=7 HEAD` puis variable d'env.
*Pourquoi :* identifier précisément quelle révision a généré chaque snapshot de données.

**8. Le repo `veille-parlementaire-sport` ne doit JAMAIS être touché.**
C'est un projet séparé en production, avec son propre pipeline. On peut le LIRE en référence (notamment pour le pattern bloc meta header) mais aucune modif.

---

## TODO

**Priorité haute (à valider au prochain run cron, lundi 27/04/2026 13h Paris)** :
- Vérifier que les 4 nouvelles URLs RSS cat.3 fonctionnent (sportbusiness.club/feed/, cafedusportbusiness.com/feed/, cosmos.asso.fr/feed/, sportexpertise.com/feed/, sport-strategies.com/feed/, lequipe.fr/rss/actu_rss.xml). Pour celles qui retournent 4xx/5xx : remplacer par scrap HTML ciblé ou retirer.
- Confirmer que `data/meta.json` est bien généré avec un `system_version` non-vide (format `v6 · abc1234`).
- Confirmer que le bloc meta s'affiche correctement dans le header de la page d'accueil après refresh.

**Priorité moyenne** :
- La cat.2 (signaux contrats) est à 0 sur le snapshot actuel. Surveiller dans les 2-3 prochaines semaines si les médias RSS publient effectivement des "X a confié sa communication à Y". Si rien ne remonte, élargir `KEYWORDS_SIGNAUX_CONTRATS` (ajouter conjugaisons passives, formes nominales).
- Si le quota SerpAPI dépasse 88/mois, ajuster le cron pour exclure aussi le mercredi (4 req × 18 jours = 72/mois).
- Récupérer les flux RSS de News Tank Sport (paywall) — actuellement scrap HTML de la home publique. Si insuffisant, abandonner cette source.

**Priorité basse** :
- Ajouter un favicon de fallback générique si le service Google S2 retourne une icône vide (rare mais arrive sur certains domaines obscurs).
- Améliorer le rendu modal d'analyse IA pour afficher le contexte de catégorie (cat.1/2/3).
- Étendre la whitelist `WHITELIST_EMETTEURS_LOCAUX_FR` avec les départements importants (Seine-Saint-Denis, Hauts-de-Seine…) si Cyril remarque que des marchés pertinents sont droppés.

**Sécurité** :
- Le token PAT GitHub `ghp_AVGhVg…` configuré dans l'URL du remote du dossier Drive a été utilisé pour push depuis la sandbox Cowork. Cyril doit le révoquer dans https://github.com/settings/tokens et passer à `gh auth login` (ou trousseau macOS) — pas encore fait au moment du handoff.

---

## Pièges connus

**1. `os.environ.get("KEY", "default")` retourne `""` si la clé existe mais est vide.**
Bug rencontré sur `SYSTEM_VERSION`. Toujours utiliser `os.environ.get("KEY") or "default"` pour fallback robuste.

**2. Refactor d'éléments DOM : penser aux références JS résiduelles.**
Le hotfix `5b65869` a corrigé un crash : suppression de `<span id="lastUpdate">` du header sans nettoyer la fonction `updateTimestamp()` qui pointait dessus → `null.textContent` → crash de l'init → spinner "Chargement…" infini. Toujours grep le JS pour les `getElementById` pointant sur un id supprimé.

**3. Cache navigateur agressif sur les fichiers HTML statiques GitHub Pages.**
Après merge d'un changement HTML/JS, faire systématiquement Cmd+Shift+R (hard refresh). Le JSON est cache-busté via `?t=Date.now()` mais pas l'HTML.

**4. Les modifs locales du dossier Drive divergent du remote.**
Le repo synchronisé sur Google Drive (`/Users/cyrilmourin/Library/CloudStorage/GoogleDrive-…/07_Veille`) garde des modifs locales (`.DS_Store`, `scraper.py` ancien) qui empêchent les `git pull` automatiques. Toujours `git stash push -u` avant pull si conflit.

**5. Doublons de `source_id` dans la liste `SOURCES`.**
Bug rencontré v6 : ajout d'une source `sport_strategies` (RSS) en parallèle d'une source HTML préexistante avec le même id → collisions dans `SOURCE_WEIGHT_BONUS` et `SOURCE_CATEGORY`. Toujours vérifier l'unicité du `source_id` quand on ajoute une source.

**6. La sandbox Cowork bloque tous les domaines hors infrastructure dev.**
On ne peut PAS tester les flux RSS depuis la sandbox (proxy bloque sportbusiness.club, sporsora.com, etc.). On ne peut PAS appeler l'API GitHub (api.github.com bloqué). On peut pusher via `git push` (github.com direct OK) mais pas créer/lister des PR via API. Pour valider une source RSS, attendre le run GitHub Actions.

**7. Les items existants pré-v6 n'avaient pas de champ `category`.**
Le JS faisait `(o.category||1) === 1` → tous les items legacy s'affichaient en cat.1 → bordel total avec les scraps LinkedIn perso visibles dans Marchés. Solution appliquée via commit `f0df07c` : migration one-shot du JSON existant. Si on ré-introduit un changement de structure JSON dans le futur, prévoir un script de migration similaire.

**8. Le cron à 11h UTC peut tourner avec 2-4h de retard sur GitHub Actions.**
Les runners free tier GitHub sont best-effort. Les commits "data: mise a jour opportunites" arrivent souvent autour de 15-17h UTC en pratique. Pas un bug, juste un fait.

**9. Le bloc fence triple-quote dans `KEYWORDS_*` est sensible aux apostrophes Unicode.**
Le scraper normalise les variantes (U+2019, U+02BC, U+2032…) via `nettoyer()`. Mais quand on AJOUTE des keywords dans le code Python, écrire avec un espace au lieu de l'apostrophe ("a confie sa communication a" au lieu de "a confié sa communication à"). C'est volontaire — `nettoyer()` strip les accents et apostrophes.

---

## Historique

- 2026-04-24 : Refonte v6 livrée — 3 catégories (Marchés/Signaux/Veille), whitelists émetteurs/orgs/domaines, mots-clés signaux contrats, exclusions nominations, nouveau scoring pondéré, bloc meta version+date dans le header, 3 onglets UI, favicons par carte, `meta.json` généré au run. Hotfix `updateTimestamp` (crash spinner). Migration one-shot du JSON existant (96 → 62 items, 34 droppés posts LinkedIn perso).
- 2026-04-19 : Audit complet livré + v5 — logique FranceMarchés stricte (26 exclusions), surpondération sources de référence (BOAMP, marches2030, TED, CNOSF), whitelist acheteurs prioritaires, normalisation Unicode NFD + apostrophes, suppression workflow dupliqué, consolidation SerpAPI 11→4 req/run × 5j/sem (~88/mois). Ajouts cat.2 sur étape v6.
