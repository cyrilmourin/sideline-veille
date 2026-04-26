# HANDOFF — sideline-veille

Note de transmission pour reprendre la maintenance du projet **Sideline Veille Marchés** (https://github.com/cyrilmourin/sideline-veille).

---

## État actuel

Le projet est en **v6.12 (2 onglets — Marchés + Veille sport business)** depuis le 25/04/2026.

**Pipeline de scraping** (`scraper.py`, ~1800 lignes) :
- 3 moteurs de détection : RSS/HTML (51 sources), SerpAPI/Google (3 requêtes consolidées), LinkedIn via SerpAPI (1 requête consolidée), plus l'API BOAMP OpenDataSoft (sans clé).
- **Pré-filtre strict** (`pre_filter`) appliqué AVANT `categorize()` : drop URLs LinkedIn `/in/`, jobs/learning, pages `/presentation-de`, `/rapports-de`, `/dossier-de-presse`, `/annonce/`, PDF hors contexte AO, domaines blacklistés (alexia.fr, profilculture, indeed, apec, the-shaperz, etc.), CPV blacklistés (92331210 animation enfants, restauration coll, transport, sécurité sociale), AO clôturés (dateLimite passée), keywords page statique (présentation/rapports/biographie) et emploi (CDI/CDD/stage/h-f/business development).
- Classification automatique en 2 catégories via `categorize(item)` (cat.2 historique fusionnée dans cat.3 le 26/04/2026, le champ existe toujours dans le code mais n'est plus retourné) :
  - **Cat.1 — Marchés réels** : appels d'offres publics formels (BOAMP, TED/JOUE, marches2030, profils acheteurs ANS/Solideo/CNOSF, France Marchés, pages /consultations des fédérations).
  - **Cat.3 — Veille sport business** : flux RSS qualifiés (SportBusiness Club, Café du Sport Biz, Sporsora, Sport Stratégies, COSMOS, GIE Sport Expertise, L'Équipe, News Tank, Sport Buzz Business). Inclut aussi les ex-signaux contrats (annonces "X a confié sa communication à Y", "remporte l'appel d'offre").
- Filtre institutionnel sur scraps Google/LinkedIn : un post de particulier est droppé sauf s'il vient d'un domaine whitelisté (linkedin.com/company/, sports.gouv.fr, boamp.fr, etc.) OU mentionne une org reconnue (UCI, FFR, COJOP 2030, etc.).
- Filtre nominations RH : drop des "nouveau directeur commercial", "prise de fonction", "nommé(e)", "promu(e)" (20 patterns).
- Whitelist 103 émetteurs locaux FR : 13 régions, 10 métropoles, ministères, agences, fédés/ligues, organisateurs grands événements (UCI 2027, Mondial Basket 2031, Euro 2028, COJOP 2030).
- Scoring pondéré par catégorie : cat.1 × 1.5, cat.2 × 1.0, cat.3 × 0.55, plus −5pts si scrap hors domaine officiel.
- Génération de `data/opportunites.json` (items) et `data/meta.json` (version + date MAJ + compteurs cat.1/2/3) à chaque run.

**Frontend** (`index.html`, page statique servie via GitHub Pages) :
- Header avec bloc meta à droite : "Données M.A.J JJ/MM/AA à HHhMM" + "Version v6 · short-sha".
- Nav à **2 onglets** sous le header avec compteur dynamique (Marchés + Veille sport business). Cat.2 historique fusionnée dans cat.3 le 26/04/2026.
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
- ~4 items en cat.1 / ~64 en cat.3 (post-purge v6.11.1, l'ordre de grandeur va remonter au prochain run complet). Sources cat.3 actives : SportBusiness Club institutions/agences/brèves, SPORSORA, Sport Buzz Business, Sport Stratégies, COSMOS, Café du Sport Biz, GIE Sport Expertise, L'Équipe sport business. Sources d'actu sportive pure (NBA, Roland Garros, Tour de France, F1, FFA, LFP, LNR) ont été supprimées car hors-cible business.

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

**5. Scoring sur-pondéré sur le métier Sideline (v6.11).**
`METIER_SIDELINE_BONUS` ajoute +8 à +22pts par mot-clé métier rencontré (cap 3 hits) : affaires publiques (+22), influence (+18), conseil stratégique (+18), communication institutionnelle (+14), droit du sport (+15), sponsoring (+12), RP (+12), gouvernance (+12). À l'inverse, `ACTU_PURE_PENALTY` retire −25pts par hit (max −50) si le contenu contient résultats/finales/billetterie/transferts/calendrier. Effet : un AO « animation enfants » ou un article « finale Coupe de France rugby » score quasi nul ; un AO « conseil affaires publiques fédération sport » ou un article « X choisit son agence pour ses RP institutionnelles » score 80-100.
*Pourquoi :* après plusieurs versions trop binaires (drop ou pass), Cyril voulait un scoring nuancé qui priorise son cœur de métier sans éliminer les marchés sport légitimes hors AP/conseil/com.

**6. Whitelist domaines + mention d'org pour scraps Google/LinkedIn.**
Un post LinkedIn de particulier est droppé SAUF s'il mentionne une organisation institutionnelle whitelistée (UCI, fédé, COJOP, ministère, etc.) — règle "mention org = OK, score bas".
*Pourquoi :* évite que tout post personnel ("Jean Dupont — mes réflexions sur le sport") pollue la veille, mais conserve les signaux légitimes (ex : "Appel à concurrence 2026 droit du sport UCI" posté par un consultant indépendant).

**7. `meta.json` séparé du JSON de données.**
`data/opportunites.json` reste un array d'items pur ; `data/meta.json` contient `updated_at_iso`, `updated_at_human`, `system_version`, et les compteurs cat.1/2/3.
*Pourquoi :* inspiré de la structure de `veille-parlementaire-sport`. Évite de casser les consommateurs JSON existants si on ajoute des métadonnées futures.

**8. `SYSTEM_VERSION` calculée dans le workflow CI, pas hardcodée.**
Format `v6 · <short-sha-7chars>` injecté via `git rev-parse --short=7 HEAD` puis variable d'env.
*Pourquoi :* identifier précisément quelle révision a généré chaque snapshot de données.

**9. Le repo `veille-parlementaire-sport` ne doit JAMAIS être touché.**
C'est un projet séparé en production, avec son propre pipeline. On peut le LIRE en référence (notamment pour le pattern bloc meta header) mais aucune modif.

**10. Pré-filtre strict avant catégorisation (v6.1).**
Le `categorize()` v6 laissait passer trop de bruit (pubs cabinet avocat, dossiers de presse PDF, AO clôturés, profils LinkedIn perso, offres d'emploi, pages "présentation de l'ANS"). On a ajouté un `pre_filter()` radical en amont qui drop sur 9 critères : domaine blacklist, pattern URL blacklist, extensions PDF/DOC suspectes hors contexte AO, mots-clés page statique, mots-clés emploi, mots-clés AO clôturé, dateLimite passée, CPV blacklist, LinkedIn restreint à /posts//pulse//feed//company//school/.
*Pourquoi :* la précision (peu de bruit) prime sur le rappel (capter tous les marchés). Mieux vaut rater un AO obscur que polluer la home avec 30 articles d'avocat. Si on veut être plus permissif on peut retirer un domaine ou un pattern individuellement.

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

**9. _parse_date() doit gérer RFC 2822 — bug v6.6→v6.9 caché par le cutoff.**
Les feeds RSS retournent leur `pubDate` en format RFC 2822 (`Fri, 24 Apr 2026 12:39:24 +0000`). Avant v6.10, `_parse_date` essayait seulement `%Y-%m-%d` → ValueError → retombait sur `datetime(2000, 1, 1)`. Conséquence : `formater_opportunite` stockait `datePublication = pubDate[:10] = "Fri, 24 Ap"` qui re-parse plus tard échouait aussi → cutoff 90 jours drop l'item du JSON final. **L'item passait scoring + était ajouté à `seen_ids`, mais disparaissait de `data/opportunites.json`**. Pendant 4 versions (v6.6 à v6.9) on a ajusté à tort le scoring/pre_filter sans voir que le bug était au cutoff. Si tu vois des items dans `seen_ids` mais pas dans `opportunites.json`, suspecte d'abord le format de date.

**10. Pré-filtre v6.1 trop agressif sur le PDF.**
Tout PDF (.pdf, .doc, .docx, .ppt, .pptx) est droppé sauf si l'URL OU le titre contient un signal AO explicite (`marche`, `consultation`, `appel-offre`, `dce`, `cahier-des-charges`, etc.). Si Cyril remonte qu'un AO légitime est droppé parce que c'est juste un PDF avec un titre vague, élargir la liste `ao_signals_url` ou `ao_signals_title` dans `pre_filter()`.

**10. Le bloc fence triple-quote dans `KEYWORDS_*` est sensible aux apostrophes Unicode.**
Le scraper normalise les variantes (U+2019, U+02BC, U+2032…) via `nettoyer()`. Mais quand on AJOUTE des keywords dans le code Python, écrire avec un espace au lieu de l'apostrophe ("a confie sa communication a" au lieu de "a confié sa communication à"). C'est volontaire — `nettoyer()` strip les accents et apostrophes.

---

## Historique

- 2026-04-26 : v6.11 + v6.12 livrées. (a) Refonte scoring métier Sideline : `METIER_SIDELINE_BONUS` (+8 à +22pts par mot-clé AP/conseil/com/sponsoring/droit du sport, cap 3 hits) + `ACTU_PURE_PENALTY` (−25pts par hit résultats/billetterie/finales/transferts). (b) Suppression des sources d'actu sportive pure (NBA, Roland Garros, Tour de France, F1, FFA, LFP, LNR) qui polluaient cat.3. (c) Filtre titre AO obligatoire pour les sources `type=federation` (drop "Accueil", "Finale Coupe", "Billetterie"…). (d) Dédup multi-source par `(titre normalisé + émetteur)` qui complète la dédup par URL canonique (un même AO peut être publié sur BOAMP RSS + BOAMP API + France Marchés avec 3 URLs différentes — Cyril voyait des triplons). (e) Fédérations classées cat.1 (au lieu de cat.3 par fallback). (f) Purge JSON one-shot des 35 items legacy hors-cible. (g) **v6.12** : fusion cat.2 dans cat.3, frontend passe de 3 onglets à 2 (Marchés + Veille). Le champ `category=2` reste toléré côté JS pour rétrocompat sur les items legacy.
- 2026-04-25 (nuit) : Épopée v6.6 → v6.10 pour faire enfin apparaître les feeds sport business (SBC, Sporsora, Sport Buzz Biz, Sport Stratégies). v6.6 baisse facteur cat.3 0.55→0.80 + seuil cat.3=12. v6.7 bypass KEYWORDS_SPORT pour cat.3 (titre "Renouvellement partenariat X" passe). v6.8 bypass KEYWORDS_PAGE_STATIQUE pour cat.3 (interview/rapport/tribune sont du contenu légitime sur SBC). v6.9 KEYWORDS_EMPLOI light pour cat.3 (drop "business development"/"sales manager" qui sont aussi des termes business). Toujours 0 SBC/Sporsora après v6.9. **Bug racine identifié v6.10** : `_parse_date` ne lisait pas RFC 2822 → datePublication des items RSS = 2000-01-01 → drop par cutoff 90j (mais après ajout à seen_ids, donc invisible dans les compteurs). Fix `email.utils.parsedate_to_datetime` + 3 fallbacks. Résultat final 200 items (limite top-200) dont 39 SBC/Sporsora/SBB/SS, top scores 80 sur articles institutionnels Alpes 2030/Conseil d'État. Aussi : retire Kingcom (agence pas généraliste), drop LinkedIn /company/ racine, dédup par URL canonique (generer_id). Workflow CI : ajout trigger `on: push` sur paths code uniquement (relance auto après modif scraper, sans boucle infinie sur data/*).
- 2026-04-25 (soir) : v6.3 livrée — fix LinkedIn /company/<slug>/ racine (page statique entreprise = drop ; seulement /company/<slug>/posts/<id> accepté). Ajout 12 domaines blacklist annuaires entreprise (pappers.fr, societe.com, manageo, infogreffe, kompass, bodacc, etc.). Correctifs sources cat.3 cassées : COSMOS asso.fr → cosmos-sports.fr (HTML), retrait sport-strategies.com (domaine inexistant), ajout fallbacks HTML pour sportbusiness.club, sport.newstank.fr/home, sporsora.com/le-mag. CPV blacklist enrichi (recrutement, formation). Migration JSON : 46 → 35 items (11 nouveaux drops dont TSM, TakeOp, CICOM SPORT, glob'AL events, Pappers SYBIOSE). UI : carte refondue avec favicon XL 56px en flag à gauche, contenu à droite (titre+score puis tags puis desc puis footer), tag-source du haut retiré.
- 2026-04-25 : v6.1 livrée — pré-filtre strict appliqué avant categorize. 9 catégories de drop (domaine blacklist, URL pattern blacklist, PDF/DOC hors AO, page statique, emploi, AO clôturé, dateLimite passée, CPV blacklist 92331210 animation enfants, LinkedIn restreint à /posts//pulse//feed//company/). Migration JSON existant : 62 → 46 items (16 nouveaux drops : alexia.fr, dossier presse PDF, jobs profilculture/welcometothejungle/fashionjobs, présentation ANS/IGESR, profils LinkedIn /in/, the-shaperz.com, etc.). Distribution finale : 25 cat.1 / 0 cat.2 / 21 cat.3.
- 2026-04-24 : Refonte v6 livrée — 3 catégories (Marchés/Signaux/Veille), whitelists émetteurs/orgs/domaines, mots-clés signaux contrats, exclusions nominations, nouveau scoring pondéré, bloc meta version+date dans le header, 3 onglets UI, favicons par carte, `meta.json` généré au run. Hotfix `updateTimestamp` (crash spinner). Migration one-shot du JSON existant (96 → 62 items, 34 droppés posts LinkedIn perso).
- 2026-04-19 : Audit complet livré + v5 — logique FranceMarchés stricte (26 exclusions), surpondération sources de référence (BOAMP, marches2030, TED, CNOSF), whitelist acheteurs prioritaires, normalisation Unicode NFD + apostrophes, suppression workflow dupliqué, consolidation SerpAPI 11→4 req/run × 5j/sem (~88/mois). Ajouts cat.2 sur étape v6.
