#!/usr/bin/env python3
"""CLI enseignant : gérer niveaux, classes, élèves, exercices et programmes."""
from __future__ import annotations

import argparse
import datetime
import getpass
import re
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_db, init_db, query_one, query_db
from app.security import hash_password

sys.path.insert(0, str(Path(__file__).resolve().parent))

from latex_extract import extract_askme, extract_askmecorrection, extract_exo_opt


def cmd_add_niveau(args):
    with get_db() as db:
        db.execute(
            "INSERT INTO devoirsfaits.niveaux (nom, programme) VALUES (%s, %s) "
            "ON CONFLICT (nom) DO NOTHING",
            (args.niveau, args.programme or ""),
        )
    print(f"Niveau {args.niveau} créé.")


def cmd_set_programme(args):
    niveau = query_one("SELECT id FROM devoirsfaits.niveaux WHERE nom = %s", (args.niveau,))
    if not niveau:
        sys.exit(f"Niveau {args.niveau} inconnu (créez-le avec add-niveau).")
    programme = args.programme
    if not programme and args.fichier:
        programme = Path(args.fichier).read_text(encoding="utf-8")
    if not programme:
        sys.exit("Fournis --programme ou --fichier.")
    with get_db() as db:
        db.execute(
            "UPDATE devoirsfaits.niveaux SET programme = %s WHERE id = %s",
            (programme, niveau["id"]),
        )
    print(f"Programme du niveau {args.niveau} mis à jour ({len(programme)} caractères).")


def cmd_add_chapitre(args):
    init_db()
    niveau = query_one("SELECT id FROM devoirsfaits.niveaux WHERE nom = %s", (args.niveau,))
    if not niveau:
        sys.exit(f"Niveau {args.niveau} inconnu (créez-le avec add-niveau).")
    contenu = args.contenu
    if not contenu and args.fichier:
        contenu = Path(args.fichier).read_text(encoding="utf-8")
    if not contenu:
        sys.exit("Fournis le contenu (argument ou --fichier).")
    with get_db() as db:
        db.execute(
            """
            INSERT INTO devoirsfaits.programme_chapitres (niveau_id, titre, contenu, ordre, transversal)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (niveau_id, titre) DO UPDATE
            SET contenu = EXCLUDED.contenu, ordre = EXCLUDED.ordre, transversal = EXCLUDED.transversal
            """,
            (niveau["id"], args.titre, contenu, args.ordre, args.transversal),
        )
    print(f"Chapitre « {args.titre} » enregistré pour {args.niveau}.")


def cmd_list_chapitres(args):
    init_db()
    rows = query_db(
        """
        SELECT n.nom AS niveau, c.titre, c.ordre, length(c.contenu) AS taille
        FROM devoirsfaits.programme_chapitres c
        JOIN devoirsfaits.niveaux n ON n.id = c.niveau_id
        ORDER BY n.nom, c.ordre, c.id
        """
    )
    for r in rows:
        print(f"{r['niveau']:<8} ordre={r['ordre']:<3} {r['taille']:>6} car.  {r['titre']}")
    if not rows:
        print("Aucun chapitre enregistré.")


def cmd_set_chapitre_exercice(args):
    """Rattache un exercice à un ou plusieurs chapitres (remplace les liaisons existantes)."""
    init_db()
    exo = query_one(
        "SELECT id FROM devoirsfaits.exercices WHERE slug = %s", (args.slug,)
    )
    if not exo:
        sys.exit(f"Exercice {args.slug} inconnu.")
    ids = []
    with get_db() as db:
        for titre_chap in args.chapitres:
            chap = query_one(
                """
                SELECT c.id, c.transversal FROM devoirsfaits.programme_chapitres c
                JOIN devoirsfaits.niveaux n ON n.id = c.niveau_id
                WHERE c.titre = %s AND n.nom = %s
                """,
                (titre_chap, args.niveau),
            )
            if not chap:
                sys.exit(f"Chapitre « {titre_chap} » inconnu pour le niveau {args.niveau}.")
            if not chap["transversal"]:
                ids.append(chap["id"])
        db.execute("DELETE FROM devoirsfaits.exercices_chapitres WHERE exercice_id = %s", (exo["id"],))
        for chap_id in ids:
            db.execute(
                "INSERT INTO devoirsfaits.exercices_chapitres (exercice_id, chapitre_id) VALUES (%s, %s)",
                (exo["id"], chap_id),
            )
    print(f"Exercice {args.slug} rattaché à {len(ids)} chapitre(s).")


def cmd_import_chapitres(args):
    """Importe tous les .txt d'un dossier : nom de fichier = titre du chapitre.
    Convention : les fichiers préfixés « transversal- » sont injectés pour tous
    les exercices ; les autres sont rattachables explicitement."""
    init_db()
    dossier = Path(args.dossier)
    if not dossier.is_dir():
        sys.exit(f"Dossier introuvable : {dossier}")
    fichiers = sorted(dossier.glob("*.txt"))
    if not fichiers:
        sys.exit("Aucun fichier .txt dans ce dossier.")
    for i, fic in enumerate(fichiers, start=1):
        titre = fic.stem
        transversal = titre.startswith("transversal-")
        if transversal:
            titre = titre[len("transversal-"):]
        args_chap = argparse.Namespace(
            niveau=args.niveau,
            titre=titre,
            contenu="",
            fichier=str(fic),
            ordre=i,
            transversal=transversal,
        )
        cmd_add_chapitre(args_chap)
    print(f"{len(fichiers)} chapitre(s) importé(s) pour {args.niveau}.")


def annee_scolaire_courante() -> str:
    """Année scolaire en cours : sept-janv -> N/N+1, févr-août -> N-1/N."""
    today = datetime.date.today()
    debut = today.year if today.month >= 9 else today.year - 1
    return f"{debut}-{debut + 1}"


def cmd_add_class(args):
    niveau = query_one("SELECT id FROM devoirsfaits.niveaux WHERE nom = %s", (args.niveau,))
    if not niveau:
        sys.exit(f"Niveau {args.niveau} inconnu (créez-le d'abord avec add-niveau).")
    with get_db() as db:
        db.execute(
            "INSERT INTO devoirsfaits.classes (nom, annee_scolaire, niveau_id) "
            "VALUES (%s, %s, %s) ON CONFLICT (nom) DO NOTHING",
            (args.classe, args.annee, niveau["id"]),
        )
    print(f"Classe {args.classe} créée ({args.annee}, niveau {args.niveau}).")


def _resolve_niveau_id(nom: str) -> int | None:
    return (query_one("SELECT id FROM devoirsfaits.niveaux WHERE nom = %s", (nom,)) or {}).get("id")


def cmd_add_exercice(args):
    niveau_id = _resolve_niveau_id(args.niveau)
    if not niveau_id:
        sys.exit(f"Niveau {args.niveau} inconnu (créez-le avec add-niveau).")
    exists = query_one("SELECT id FROM devoirsfaits.exercices WHERE slug = %s", (args.slug,))
    if exists:
        sys.exit(f"Exercice {args.slug} existe déjà.")

    def read_field(text, fichier):
        if text:
            return text
        if fichier:
            return Path(fichier).read_text(encoding="utf-8").strip()
        return input("Valeur: ").strip()

    enonce = read_field(args.enonce, args.fichier_enonce)
    correction = read_field(args.correction, args.fichier_correction)
    with get_db() as db:
        db.execute(
            "INSERT INTO devoirsfaits.exercices (niveau_id, slug, titre, enonce, correction) "
            "VALUES (%s, %s, %s, %s, %s)",
            (niveau_id, args.slug, args.titre, enonce, correction),
        )
    print(f"Exercice {args.slug} ({args.titre}) ajouté au niveau {args.niveau}.")


def cmd_add_student(args):
    classe = query_one("SELECT id FROM devoirsfaits.classes WHERE nom = %s", (args.classe,))
    if not classe:
        sys.exit(f"Classe {args.classe} inconnue.")
    exists = query_one("SELECT id FROM devoirsfaits.eleves WHERE login = %s", (args.login,))
    if exists:
        sys.exit(f"Login {args.login} déjà pris.")
    password = args.password or getpass.getpass(f"Mot de passe pour {args.prenom} {args.nom} : ")
    if len(password) < 4:
        sys.exit("Mot de passe trop court (min 4 caractères).")
    with get_db() as db:
        db.execute(
            "INSERT INTO devoirsfaits.eleves (classe_id, login, nom, prenom, password_hash) "
            "VALUES (%s, %s, %s, %s, %s)",
            (classe["id"], args.login, args.nom, args.prenom, hash_password(password)),
        )
    print(f"Élève {args.prenom} {args.nom} créé — login : {args.login}")


def _random_password(length: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def cmd_reset_password(args):
    eleve = query_one("SELECT id, login, nom, prenom FROM devoirsfaits.eleves WHERE login = %s", (args.login,))
    if not eleve:
        sys.exit(f"Login {args.login} inconnu.")
    password = _random_password()
    with get_db() as db:
        db.execute(
            "UPDATE devoirsfaits.eleves SET password_hash = %s WHERE id = %s",
            (hash_password(password), eleve["id"]),
        )
    print(f"{eleve['prenom']} {eleve['nom']} — login : {args.login} — mot de passe : {password}")


ELEVE_LINE_RE = re.compile(r"^(.*?);\s*([MF])\s*$")


def _login_from_name(nom_complet: str) -> str:
    parts = nom_complet.strip().split()
    prenom = parts[-1].lower()
    initiales = "".join(p[0].lower() for p in parts[:-1]) or "x"
    base = f"{prenom}.{initiales}"
    login = base
    suffix = 2
    while query_one("SELECT id FROM devoirsfaits.eleves WHERE login = %s", (login,)):
        login = f"{base}{suffix}"
        suffix += 1
    return login


def cmd_import_eleves(args):
    classe = query_one("SELECT id FROM devoirsfaits.classes WHERE nom = %s", (args.classe,))
    if not classe:
        sys.exit(f"Classe {args.classe} inconnue (créez-la d'abord avec add-class).")
    lines = [
        ln.strip()
        for ln in Path(args.fichier).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    if not lines:
        sys.exit("Fichier vide.")
    niveau_nom = lines[0].strip()
    niveau_id = _resolve_niveau_id(niveau_nom)
    if not niveau_id:
        sys.exit(f"Niveau {niveau_nom} inconnu (créez-le avec add-niveau).")
    rows = []
    for ln in lines[1:]:
        m = ELEVE_LINE_RE.match(ln)
        if not m:
            print(f"⚠ ligne ignorée (format inattendu) : {ln}")
            continue
        nom_complet = re.sub(r"\s+", " ", m.group(1).strip())
        rows.append(nom_complet)
    if not rows:
        sys.exit("Aucun élève trouvé dans le fichier.")

    created, skipped = 0, 0
    with get_db() as db:
        for nom_complet in rows:
            login = _login_from_name(nom_complet)
            exists = query_one(
                "SELECT id FROM devoirsfaits.eleves WHERE login = %s", (login,)
            )
            if exists:
                print(f"⚠ {login} existe déjà — {nom_complet} ignoré")
                skipped += 1
                continue
            parts = nom_complet.split()
            prenom, nom = parts[-1], " ".join(parts[:-1])
            password = login
            db.execute(
                "INSERT INTO devoirsfaits.eleves (classe_id, login, nom, prenom, password_hash) "
                "VALUES (%s, %s, %s, %s, %s)",
                (classe["id"], login, nom, prenom, hash_password(password)),
            )
            created += 1
    print(f"Import terminé : {created} élève(s) créé(s), {skipped} ignoré(s). "
          f"Mot de passe initial = login (à faire changer).")


def cmd_list_students(args):
    rows = query_db(
        """
        SELECT e.login, e.prenom, e.nom, c.nom AS classe
        FROM devoirsfaits.eleves e JOIN devoirsfaits.classes c ON c.id = e.classe_id
        ORDER BY c.nom, e.nom
        """
    )
    if not rows:
        print("Aucun élève.")
        return
    print(f"{'LOGIN':<20} {'CLASSE':<8} NOM")
    for r in rows:
        print(f"{r['login']:<20} {r['classe']:<8} {r['prenom']} {r['nom']}")


def cmd_list_exercices(args):
    rows = query_db(
        """
        SELECT x.slug, x.titre, n.nom AS niveau
        FROM devoirsfaits.exercices x JOIN devoirsfaits.niveaux n ON n.id = x.niveau_id
        ORDER BY n.nom, x.slug
        """
    )
    if not rows:
        print("Aucun exercice.")
        return
    print(f"{'SLUG':<28} {'NIVEAU':<10} TITRE")
    for r in rows:
        print(f"{r['slug']:<28} {r['niveau']:<10} {r['titre']}")


def cmd_sync(args):
    """Synchronise les exercices depuis un ou plusieurs fichiers .tex."""
    exercices: dict[str, dict] = {}
    corrections: dict[str, str] = {}
    for fichier in args.fichiers:
        if not Path(fichier).exists():
            sys.exit(f"Fichier introuvable : {fichier}")
        with open(fichier, encoding="utf-8") as f:
            content = f.read()
        exos = extract_askme(content)
        exos += extract_exo_opt(content, env_names=tuple(args.exo_env or ("exo", "exercice", "Exo")))
        cors = extract_askmecorrection(content)
        for exo in exos:
            if exo["slug"] in exercices:
                continue
            if not exo.get("niveau") and args.niveau:
                exo["niveau"] = args.niveau
            exercices[exo["slug"]] = exo
        corrections.update(cors)

    if not exercices and not corrections:
        sys.exit(
            "Aucun exercice trouvé. Vérifiez que vos exercices utilisent "
            "\\begin{exo}[slug] ou \\begin{askme}{slug}{titre}{niveau}."
        )

    created, updated = 0, 0
    with get_db() as db:
        for slug, exo in exercices.items():
            niveau_id = _resolve_niveau_id(exo["niveau"]) if exo.get("niveau") else None
            if not niveau_id:
                print(f"⚠ niveau {exo.get('niveau') or '(manquant — utilisez --niveau)'} inconnu — exo {slug} ignoré (créez-le d'abord)")
                continue
            correction = corrections.get(slug, "")
            existing = query_one(
                "SELECT id FROM devoirsfaits.exercices WHERE slug = %s", (slug,)
            )
            if existing:
                db.execute(
                    "UPDATE devoirsfaits.exercices SET niveau_id = %s, titre = %s, "
                    "enonce = %s, correction = %s WHERE id = %s",
                    (niveau_id, exo["titre"], exo["enonce"], correction, existing["id"]),
                )
                updated += 1
            else:
                db.execute(
                    "INSERT INTO devoirsfaits.exercices (niveau_id, slug, titre, enonce, correction) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (niveau_id, slug, exo["titre"], exo["enonce"], correction),
                )
                created += 1
        for slug, correction in corrections.items():
            if slug not in exercices:
                existing = query_one(
                    "SELECT id, correction FROM devoirsfaits.exercices WHERE slug = %s", (slug,)
                )
                if existing and not existing["correction"]:
                    db.execute(
                        "UPDATE devoirsfaits.exercices SET correction = %s WHERE id = %s",
                        (correction, existing["id"]),
                    )
    print(f"Sync terminé : {created} créé(s), {updated} mis à jour.")


def cmd_seed_demo(args):
    init_db()
    programme_3e = (
        "Programme de mathématiques 3e (2025-2026) :\n"
        "- Nombres et calculs : puissances, notation scientifique, arithmétique (diviseurs, PGCD), fractions.\n"
        "- Calcul littéral : développements, factorisations, équations du premier degré.\n"
        "- Géométrie : théorème de Thalès, trigonométrie, angles inscrits.\n"
        "- Fonctions : notions de fonction, fonctions affines et linéaires.\n"
        "- Statistiques et probabilités."
    )
    with get_db() as db:
        db.execute(
            "INSERT INTO devoirsfaits.niveaux (nom, programme) VALUES (%s, %s) "
            "ON CONFLICT (nom) DO NOTHING",
            ("3e", programme_3e),
        )
        db.execute(
            "INSERT INTO devoirsfaits.niveaux (nom, programme) VALUES (%s, %s) "
            "ON CONFLICT (nom) DO NOTHING",
            ("4e", "Programme de mathématiques 4e (2025-2026) : fractions, Pythagore, calcul littéral."),
        )
        db.execute(
            "INSERT INTO devoirsfaits.classes (nom, annee_scolaire, niveau_id) "
            "SELECT %s, %s, id FROM devoirsfaits.niveaux WHERE nom = '3e' "
            "ON CONFLICT (nom) DO NOTHING",
            ("3A", "2025-2026"),
        )
        db.execute(
            "INSERT INTO devoirsfaits.classes (nom, annee_scolaire, niveau_id) "
            "SELECT %s, %s, id FROM devoirsfaits.niveaux WHERE nom = '4e' "
            "ON CONFLICT (nom) DO NOTHING",
            ("4B", "2025-2026"),
        )
        niveau_id = db.execute(
            "SELECT id FROM devoirsfaits.niveaux WHERE nom = '3e'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO devoirsfaits.exercices (niveau_id, slug, titre, enonce, correction) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (slug) DO NOTHING",
            (
                niveau_id,
                "ex-pgcd-01",
                "PGCD - Exercice 1",
                "Déterminer le PGCD de 120 et 84. En déduire la forme irréductible de la fraction 84/120.",
                (
                    "1) On décompose en facteurs premiers : 120 = 2³ × 3 × 5 et 84 = 2² × 3 × 7.\n"
                    "2) Le PGCD est le produit des facteurs premiers communs avec le plus petit exposant : "
                    "PGCD(120, 84) = 2² × 3 = 12.\n"
                    "3) On simplifie : 84/120 = (84 ÷ 12)/(120 ÷ 12) = 7/10."
                ),
            ),
        )
        db.execute(
            "INSERT INTO devoirsfaits.exercices (niveau_id, slug, titre, enonce, correction) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (slug) DO NOTHING",
            (
                niveau_id,
                "ex-thales-01",
                "Thalès - Exercice 1",
                "Les droites (BC) et (DE) sont parallèles. On donne AB = 4 cm, AC = 6 cm, AD = 6 cm. Calculer AE.",
                (
                    "1) Les droites (BC) et (DE) sont parallèles, les points A, B, D et A, C, E sont alignés "
                    "dans le même ordre : d'après le théorème de Thalès, AB/AD = AC/AE.\n"
                    "2) On remplace : 4/6 = 6/AE.\n"
                    "3) Donc AE = (6 × 6)/4 = 9. AE mesure 9 cm."
                ),
            ),
        )
        classe_id = db.execute(
            "SELECT id FROM devoirsfaits.classes WHERE nom = '3A'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO devoirsfaits.eleves (classe_id, login, nom, prenom, password_hash) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (login) DO NOTHING",
            (classe_id, "lucie.d", "Dupont", "Lucie", hash_password("demo1234")),
        )
        db.execute(
            "INSERT INTO devoirsfaits.eleves (classe_id, login, nom, prenom, password_hash) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (login) DO NOTHING",
            (classe_id, "hugo.m", "Martin", "Hugo", hash_password("demo1234")),
        )
    print("Données de démo prêtes : niveaux 3e/4e, classes 3A et 4B, exercices ex-pgcd-01 "
          "et ex-thales-01, élèves lucie.d / hugo.m (mdp : demo1234).")


def main():
    parser = argparse.ArgumentParser(description="Gestion exo")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add-niveau", help="Créer un niveau (ex: 2nde, tsti2d)")
    p.add_argument("niveau")
    p.add_argument("--programme", default="")
    p.set_defaults(fn=cmd_add_niveau)

    p = sub.add_parser("set-programme", help="Définir le programme d'un niveau")
    p.add_argument("niveau")
    p.add_argument("--programme", default="")
    p.add_argument("--fichier", help="Fichier texte contenant le programme")
    p.set_defaults(fn=cmd_set_programme)

    p = sub.add_parser("add-chapitre", help="Ajouter/mettre à jour un chapitre de programme")
    p.add_argument("niveau")
    p.add_argument("titre")
    p.add_argument("--contenu", default="")
    p.add_argument("--fichier", help="Fichier texte contenant le chapitre")
    p.add_argument("--ordre", type=int, default=0)
    p.add_argument("--transversal", action="store_true", help="Chapitre injecté pour tous les exercices")
    p.set_defaults(fn=cmd_add_chapitre)

    p = sub.add_parser("import-chapitres", help="Importer tous les fichiers .txt d'un dossier comme chapitres")
    p.add_argument("niveau")
    p.add_argument("dossier")
    p.set_defaults(fn=cmd_import_chapitres)

    p = sub.add_parser("list-chapitres", help="Lister les chapitres de programme")
    p.set_defaults(fn=cmd_list_chapitres)

    p = sub.add_parser("set-chapitre-exercice", help="Rattacher un exercice à un ou plusieurs chapitres")
    p.add_argument("slug")
    p.add_argument("niveau")
    p.add_argument("chapitres", nargs="+")
    p.set_defaults(fn=cmd_set_chapitre_exercice)

    p = sub.add_parser("add-class", help="Créer une classe rattachée à un niveau")
    p.add_argument("classe")
    p.add_argument("--niveau", required=True, help="Niveau (ex: 2nde)")
    p.add_argument("--annee", default=annee_scolaire_courante(),
                   help="Par défaut : année scolaire en cours")
    p.set_defaults(fn=cmd_add_class)

    p = sub.add_parser("add-exercice", help="Ajouter un exercice à un niveau")
    p.add_argument("niveau")
    p.add_argument("slug", help="Identifiant unique, ex: ex-pgcd-01")
    p.add_argument("--titre", required=True)
    p.add_argument("--enonce", default="")
    p.add_argument("--fichier-enonce")
    p.add_argument("--correction", default="")
    p.add_argument("--fichier-correction")
    p.set_defaults(fn=cmd_add_exercice)

    p = sub.add_parser("add-student", help="Créer un compte élève")
    p.add_argument("classe")
    p.add_argument("nom")
    p.add_argument("prenom")
    p.add_argument("--login", required=True)
    p.add_argument("--password", help="Sinon, demandé interactivement")
    p.set_defaults(fn=cmd_add_student)

    p = sub.add_parser("reset-password", help="Réinitialiser le mot de passe d'un élève (génère 6 caractères aléatoires)")
    p.add_argument("login")
    p.set_defaults(fn=cmd_reset_password)
    p = sub.add_parser("import-eleves", help="Importer une classe depuis un fichier eleves.txt")
    p.add_argument("classe", help="Classe cible (doit exister)")
    p.add_argument("fichier", help="Fichier eleves.txt (1re ligne = niveau)")
    p.set_defaults(fn=cmd_import_eleves)

    p = sub.add_parser("list-students", help="Lister les élèves")
    p.set_defaults(fn=cmd_list_students)

    p = sub.add_parser("list-exercices", help="Lister les exercices")
    p.set_defaults(fn=cmd_list_exercices)

    p = sub.add_parser("sync", help="Synchroniser les exercices depuis des fichiers .tex")
    p.add_argument("fichiers", nargs="+", help="Fichiers .tex (feuille + corrigé)")
    p.add_argument("--niveau", help="Niveau par défaut pour les \\begin{exo}[slug] sans \\askmeniveau")
    p.add_argument("--exo-env", nargs="*", default=[], help="Noms des environnements exo à extraire (défaut : exo exercice Exo)")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("seed-demo", help="Données de démonstration")
    p.set_defaults(fn=cmd_seed_demo)

    args = parser.parse_args()
    init_db()
    args.fn(args)


if __name__ == "__main__":
    main()
