"""Catalogue des meubles, lu depuis les manifest.json (format de pixel-agents).

Le même catalogue sert à la simulation (emprise au sol, rangées
d'arrière-plan, variantes d'orientation) et au rendu (fichiers PNG, états,
images d'animation). Ce module ne charge AUCUNE image : il ne lit que du JSON,
il reste donc utilisable sans pygame.

Structure d'un manifest (voir pixel-agents/docs/external-assets.md) :
- un `asset` simple, ou un `group` dont les membres sont des assets ou des
  groupes : `rotation` (orientations front/back/side), `state` (on/off),
  `animation` (images successives) ;
- `backgroundTiles` : nombre de rangées du haut qui ne touchent pas le sol
  (le sprite « dépasse » vers le haut, sur le mur ou derrière l'objet).

Convention de pixel-agents reprise ici : l'orientation « left » n'a pas de
dessin propre, c'est la vue « side » retournée en miroir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_STATE = "default"


class CatalogError(Exception):
    """Manifest illisible ou incohérent."""


@dataclass(frozen=True, slots=True)
class SpriteRef:
    asset_id: str
    file: Path
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Variant:
    orientation: str  # front, back, side, left
    footprint: tuple[int, int]
    size: tuple[int, int]
    mirrored: bool
    # état ("default", "off", "on"...) → images de l'animation, dans l'ordre
    states: dict[str, tuple[SpriteRef, ...]]

    def frames(self, state: str) -> tuple[SpriteRef, ...]:
        if state in self.states:
            return self.states[state]
        if "off" in self.states:
            return self.states["off"]
        return next(iter(self.states.values()))


@dataclass(frozen=True, slots=True)
class FurnitureSpec:
    id: str
    name: str
    category: str
    background_tiles: int
    on_walls: bool
    on_surfaces: bool
    variants: dict[str, Variant]
    overlays: dict[str, Path] = field(default_factory=dict)

    def variant(self, orientation: str) -> Variant:
        try:
            return self.variants[orientation]
        except KeyError:
            raise CatalogError(
                f"{self.id} n'a pas d'orientation {orientation!r} "
                f"(disponibles : {', '.join(self.variants)})"
            ) from None

    @property
    def default_orientation(self) -> str:
        return "front" if "front" in self.variants else next(iter(self.variants))


class Catalog:
    def __init__(self, specs: dict[str, FurnitureSpec]) -> None:
        self.specs = specs

    def __contains__(self, type_id: str) -> bool:
        return type_id in self.specs

    def get(self, type_id: str) -> FurnitureSpec:
        try:
            return self.specs[type_id]
        except KeyError:
            raise CatalogError(f"meuble inconnu : {type_id!r}") from None


def load_catalog(*roots: Path) -> Catalog:
    """Lit tous les `furniture/<ID>/manifest.json` des dossiers donnés, dans l'ordre.

    En cas de doublon, le dernier dossier l'emporte : on pourra ainsi charger
    un pack externe qui remplace un meuble de base.
    """
    specs: dict[str, FurnitureSpec] = {}
    for root in roots:
        furniture_dir = root / "furniture"
        if not furniture_dir.is_dir():
            raise CatalogError(f"dossier de meubles introuvable : {furniture_dir}")
        for manifest_path in sorted(furniture_dir.glob("*/manifest.json")):
            spec = _parse_manifest(manifest_path)
            specs[spec.id] = spec
    return Catalog(specs)


# --------------------------------------------------------------------------- #
# Lecture d'un manifest
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class _Collected:
    orientation: str
    state: str
    frame: int
    ref: SpriteRef
    footprint: tuple[int, int]


def _parse_manifest(path: Path) -> FurnitureSpec:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"manifest illisible {path} : {exc}") from exc

    folder = path.parent
    top_id = str(data["id"])
    collected: list[_Collected] = []
    _walk(data, folder, top_id, "front", DEFAULT_STATE, 0, collected)
    if not collected:
        raise CatalogError(f"{path} : aucun sprite déclaré")

    variants: dict[str, Variant] = {}
    for orientation in dict.fromkeys(item.orientation for item in collected):
        items = [item for item in collected if item.orientation == orientation]
        states: dict[str, list[_Collected]] = {}
        for item in items:
            states.setdefault(item.state, []).append(item)
        first = items[0]
        variants[orientation] = Variant(
            orientation=orientation,
            footprint=first.footprint,
            size=(first.ref.width, first.ref.height),
            mirrored=False,
            states={
                state: tuple(entry.ref for entry in sorted(entries, key=lambda e: e.frame))
                for state, entries in states.items()
            },
        )
    if "side" in variants and "left" not in variants:
        side = variants["side"]
        variants["left"] = Variant("left", side.footprint, side.size, True, side.states)

    overlays = {
        str(name): folder / str(file) for name, file in dict(data.get("overlays", {})).items()
    }
    return FurnitureSpec(
        id=top_id,
        name=str(data.get("name", top_id)),
        category=str(data.get("category", "misc")),
        background_tiles=int(data.get("backgroundTiles", 0) or 0),
        on_walls=bool(data.get("canPlaceOnWalls", False)),
        on_surfaces=bool(data.get("canPlaceOnSurfaces", False)),
        variants=variants,
        overlays=overlays,
    )


def _walk(
    node: dict[str, Any],
    folder: Path,
    top_id: str,
    orientation: str,
    state: str,
    frame: int,
    out: list[_Collected],
) -> None:
    orientation = str(node.get("orientation") or orientation)
    state = str(node.get("state") or state)
    frame = int(node.get("frame", frame) or 0)
    if node.get("type", "asset") == "asset":
        asset_id = str(node.get("id") or top_id)
        file = folder / str(node.get("file") or f"{asset_id}.png")
        if not file.is_file():
            raise CatalogError(f"{folder.name} : image manquante {file.name}")
        width, height = int(node["width"]), int(node["height"])
        footprint = (int(node.get("footprintW", 1)), int(node.get("footprintH", 1)))
        out.append(
            _Collected(
                orientation, state, frame, SpriteRef(asset_id, file, width, height), footprint
            )
        )
        return
    for member in node.get("members", []):
        _walk(member, folder, top_id, orientation, state, frame, out)
