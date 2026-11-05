"""Préréglages du studio : métiers, façons de parler, idéologies, noms.

Pourquoi des métiers « tout faits » plutôt qu'un éditeur d'horaires ?
Parce qu'un horaire libre ouvre la porte à des journées impossibles (travail
de 22 h à 6 h, que le planificateur ne gère pas encore). Un préréglage est
cohérent par construction : lieu de travail valide, horaires, réveil et
coucher qui vont ensemble. On ouvrira plus tard quand le moteur suivra.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")
SIX_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat")


@dataclass(frozen=True, slots=True)
class JobPreset:
    key: str
    label: str  # le métier tel qu'il apparaît (« Boulanger »)
    place: str | None  # lieu de travail (None : sans emploi, retraité)
    schedule: dict[str, str]
    wake: str
    bed: str
    weekend_wake: str
    lunch_at_work: bool = False
    wage: float = 0.0  # € de l'heure
    allowance: float = 0.0  # € par jour (retraite, bourse, allocation)


def _days(days: tuple[str, ...], hours: str) -> dict[str, str]:
    return dict.fromkeys(days, hours)


JOBS: tuple[JobPreset, ...] = (
    JobPreset(
        "boulanger",
        "Boulanger",
        "boulangerie",
        _days(SIX_DAYS, "05:00-13:00"),
        "03:45",
        "21:00",
        "07:30",
        wage=14,
    ),
    JobPreset(
        "vendeur_boulangerie",
        "Vendeur en boulangerie",
        "boulangerie",
        _days(SIX_DAYS, "07:00-14:00"),
        "06:00",
        "22:00",
        "08:30",
        wage=11.5,
    ),
    JobPreset(
        "barista",
        "Barista",
        "cafe",
        _days(("tue", "wed", "thu", "fri", "sat", "sun"), "07:00-15:00"),
        "06:15",
        "23:00",
        "06:15",
        lunch_at_work=True,
        wage=12,
    ),
    JobPreset(
        "serveur",
        "Serveur",
        "cafe",
        _days(SIX_DAYS, "11:00-19:00"),
        "08:30",
        "23:30",
        "09:30",
        lunch_at_work=True,
        wage=12,
    ),
    JobPreset(
        "caissier",
        "Caissier",
        "supermarche",
        _days(("mon", "tue", "thu", "fri", "sat"), "09:00-18:30"),
        "07:30",
        "23:00",
        "09:30",
        wage=12,
    ),
    JobPreset(
        "employe_bureau",
        "Employé de bureau",
        "bureaux",
        _days(WEEKDAYS, "09:00-17:30"),
        "07:00",
        "23:00",
        "09:00",
        wage=15,
    ),
    JobPreset(
        "comptable",
        "Comptable",
        "bureaux",
        _days(WEEKDAYS, "09:00-17:30"),
        "07:00",
        "23:00",
        "09:00",
        wage=18,
    ),
    JobPreset(
        "developpeur",
        "Développeur",
        "bureaux",
        _days(WEEKDAYS, "10:00-18:30"),
        "08:00",
        "23:30",
        "10:00",
        wage=22,
    ),
    JobPreset(
        "professeur",
        "Professeur des écoles",
        "ecole",
        {**_days(("mon", "tue", "thu", "fri"), "08:20-16:30"), "wed": "08:20-12:00"},
        "06:30",
        "22:30",
        "08:00",
        wage=17,
    ),
    # Étape 6 ter : les nouveaux commerces de la ville.
    JobPreset(
        "croupier",
        "Croupier",
        "casino",
        _days(("wed", "thu", "fri", "sat", "sun"), "14:30-22:30"),
        "09:30",
        "23:30",
        "09:30",
        wage=15,
    ),
    JobPreset(
        "barman",
        "Barman",
        "bar",
        _days(("tue", "wed", "thu", "fri", "sat"), "17:00-23:00"),
        "09:30",
        "23:30",
        "10:00",
        wage=13,
    ),
    JobPreset(
        "vendeur_mode",
        "Vendeur en boutique",
        "boutique",
        _days(SIX_DAYS, "10:00-19:00"),
        "08:00",
        "23:00",
        "09:00",
        wage=12,
    ),
    JobPreset(
        "vendeur_hitech",
        "Vendeur hi-tech",
        "hitech",
        _days(SIX_DAYS, "10:00-19:00"),
        "08:00",
        "23:00",
        "09:00",
        wage=13,
    ),
    JobPreset("retraite", "Retraité", None, {}, "07:00", "22:00", "07:30", allowance=55),
    JobPreset("etudiant", "Étudiant", None, {}, "08:30", "23:30", "10:30", allowance=22),
    JobPreset(
        "sans_emploi", "En recherche d'emploi", None, {}, "08:00", "23:00", "09:00", allowance=32
    ),
)
JOBS_BY_KEY = {job.key: job for job in JOBS}


def job_for(label: str, place: str | None) -> JobPreset:
    """Retrouve le préréglage d'un habitant existant (par lieu, puis par intitulé)."""
    for job in JOBS:
        if job.label == label and job.place == place:
            return job
    for job in JOBS:
        if job.place == place:
            return job
    return JOBS_BY_KEY["retraite"]


SPEECH_STYLES: tuple[str, ...] = (
    "chaleureux, tutoie facilement, beaucoup d'humour",
    "poli et un peu formel, vouvoie toujours",
    "phrases courtes, direct, parfois sec",
    "bavard, digresse et raconte des anecdotes",
    "argot jeune, décontracté, abrège les mots",
    "timide, hésite, parle peu",
    "pédagogue, pose des questions, explique",
    "ironique, aime taquiner",
    "nostalgique, compare tout au passé",
    "enthousiaste, s'exclame souvent",
)

IDEOLOGIES: tuple[str, ...] = (
    "",
    "écologiste convaincu : consommer local, réduire ses déchets",
    "libéral : l'initiative individuelle et la liberté d'entreprendre avant tout",
    "attaché aux traditions, à la famille et à la vie de quartier",
    "progressiste, sensible à l'égalité et aux droits de chacun",
    "pragmatique, se méfie des grands discours",
    "technophile : la technologie va résoudre la plupart des problèmes",
    "décroissant : moins d'écrans, moins d'achats, plus de lien",
    "sceptique envers la publicité et les grandes marques",
    "épicurien : profiter de la vie, bien manger, bien recevoir",
)

ACCENT_COLORS: tuple[str, ...] = (
    "#d08c45",
    "#5b8def",
    "#4caf7d",
    "#e07ab0",
    "#f0b429",
    "#9b8cd6",
    "#e05d5d",
    "#3fbac2",
    "#8bc34a",
    "#ff8a65",
    "#b0bec5",
    "#c58af9",
)

FIRST_NAMES = (
    "Camille",
    "Louis",
    "Chloé",
    "Nathan",
    "Inès",
    "Jules",
    "Manon",
    "Yanis",
    "Sarah",
    "Lucas",
    "Emma",
    "Mehdi",
    "Zoé",
    "Gabriel",
    "Lina",
    "Arthur",
    "Jade",
    "Adam",
    "Clara",
    "Noah",
    "Agathe",
    "Bastien",
    "Fatou",
    "Théo",
    "Nadia",
    "Victor",
    "Elsa",
    "Rayan",
)
LAST_NAMES = (
    "Bernard",
    "Petit",
    "Durand",
    "Leroy",
    "Moreau",
    "Simon",
    "Laurent",
    "Lefebvre",
    "Michel",
    "Garcia",
    "David",
    "Bertrand",
    "Roux",
    "Vincent",
    "Fournier",
    "Morel",
    "Girard",
    "Andre",
    "Mercier",
    "Blanc",
    "Guerin",
    "Boyer",
    "Diallo",
    "Nguyen",
    "Haddad",
    "Costa",
)
VALUES = (
    "la famille",
    "l'amitié",
    "le travail bien fait",
    "la liberté",
    "la curiosité",
    "la justice",
    "la nature",
    "la musique",
    "le sport",
    "la réussite",
    "la tranquillité",
    "la générosité",
    "l'humour",
    "la tradition",
    "la créativité",
    "l'honnêteté",
    "les voyages",
    "la cuisine",
)


def slugify(text: str) -> str:
    """« Léa Martin » → « lea_martin » : un identifiant sûr pour YAML et les fichiers."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = "h_" + slug
    return slug[:40]


def random_name(rng: random.Random, taken: set[str]) -> str:
    for _ in range(50):
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if name not in taken:
            return name
    return f"Habitant {len(taken) + 1}"
