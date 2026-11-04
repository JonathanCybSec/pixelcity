"""Lecteur minimal de cartes Tiled (.tmx), SANS pygame.

Pourquoi ne pas utiliser pytmx ici ? Parce que `import pytmx` importe pygame
de lui-même (son `__init__.py` charge ses outils pygame dès qu'il le peut).
L'utiliser dans le noyau ferait entrer pygame dans le mode headless et
casserait la frontière simulation / rendu. Le test `test_boundary.py` l'a
détecté : c'est exactement son rôle.

Répartition retenue :
- la simulation lit la carte avec ce module (géométrie, propriétés, objets) ;
- le rendu utilise pytmx (`engine/renderer.py`), qui découpe les images.

Ce lecteur gère ce que Tiled produit pour une carte orthogonale classique :
couches de tuiles (CSV ou base64, compressées zlib/gzip ou non), tilesets
intégrés ou externes (.tsx), propriétés de tuiles, calques d'objets.

Note sécurité : les cartes sont ici des fichiers locaux de confiance. Pour
charger des cartes venues d'Internet (mods, partage), on passerait par
`defusedxml`, qui bloque les attaques XML connues (entités récursives, etc.).
"""

from __future__ import annotations

import base64
import gzip
import struct
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path

type PropertyValue = str | int | float | bool

# Tiled stocke les retournements d'une tuile (horizontal, vertical, diagonal,
# rotation hexagonale) dans les 4 bits de poids fort de son identifiant.
# On les retire pour retrouver l'identifiant réel (GID).
_GID_MASK = 0x0FFFFFFF


class TmxError(Exception):
    """Carte illisible ou dans un format non géré."""


@dataclass(frozen=True, slots=True)
class TmxObject:
    id: int
    name: str
    x: float
    y: float
    width: float
    height: float
    properties: dict[str, PropertyValue]


@dataclass(frozen=True, slots=True)
class TmxMap:
    width: int
    height: int
    tile_width: int
    tile_height: int
    layers: dict[str, tuple[int, ...]]
    object_groups: dict[str, tuple[TmxObject, ...]]
    tile_properties: dict[int, dict[str, PropertyValue]]

    def gid_at(self, layer: str, x: int, y: int) -> int:
        return self.layers[layer][y * self.width + x]


def load_tmx(path: Path) -> TmxMap:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise TmxError(f"impossible de lire la carte {path} : {exc}") from exc

    if root.get("orientation", "orthogonal") != "orthogonal":
        raise TmxError("seules les cartes orthogonales sont gérées")
    if root.get("infinite", "0") == "1":
        raise TmxError("les cartes « infinies » de Tiled ne sont pas gérées (décochez Infinite)")

    width, height = int(root.attrib["width"]), int(root.attrib["height"])
    tile_properties: dict[int, dict[str, PropertyValue]] = {}
    for tileset in root.iter("tileset"):
        tile_properties.update(_read_tileset(tileset, path.parent))

    layers: dict[str, tuple[int, ...]] = {}
    for layer in root.iter("layer"):
        name = layer.get("name", "")
        data = layer.find("data")
        if data is None:
            raise TmxError(f"couche {name!r} sans données")
        gids = _decode_layer_data(data, name)
        if len(gids) != width * height:
            raise TmxError(f"couche {name!r} : {len(gids)} tuiles au lieu de {width * height}")
        layers[name] = gids

    object_groups: dict[str, tuple[TmxObject, ...]] = {}
    for group in root.iter("objectgroup"):
        object_groups[group.get("name", "")] = tuple(
            TmxObject(
                id=int(obj.get("id", "0")),
                name=obj.get("name", ""),
                x=float(obj.get("x", "0")),
                y=float(obj.get("y", "0")),
                width=float(obj.get("width", "0")),
                height=float(obj.get("height", "0")),
                properties=_read_properties(obj),
            )
            for obj in group.iter("object")
        )

    return TmxMap(
        width=width,
        height=height,
        tile_width=int(root.attrib["tilewidth"]),
        tile_height=int(root.attrib["tileheight"]),
        layers=layers,
        object_groups=object_groups,
        tile_properties=tile_properties,
    )


def _read_tileset(element: ET.Element, base_dir: Path) -> dict[int, dict[str, PropertyValue]]:
    first_gid = int(element.attrib["firstgid"])
    source = element.get("source")
    if source is not None:
        # Tileset externe (.tsx) : son chemin est relatif au fichier .tmx.
        try:
            element = ET.parse(base_dir / source).getroot()
        except (OSError, ET.ParseError) as exc:
            raise TmxError(f"tileset externe illisible {source!r} : {exc}") from exc
    return {
        first_gid + int(tile.attrib["id"]): _read_properties(tile) for tile in element.iter("tile")
    }


def _read_properties(element: ET.Element) -> dict[str, PropertyValue]:
    properties: dict[str, PropertyValue] = {}
    container = element.find("properties")
    if container is None:
        return properties
    for prop in container.iter("property"):
        name = prop.attrib["name"]
        # Une valeur longue peut être écrite comme texte de l'élément.
        raw = prop.get("value", prop.text or "")
        kind = prop.get("type", "string")
        properties[name] = _convert(raw, kind)
    return properties


def _convert(raw: str, kind: str) -> PropertyValue:
    if kind == "bool":
        return raw == "true"
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    return raw


def _decode_layer_data(data: ET.Element, layer_name: str) -> tuple[int, ...]:
    encoding = data.get("encoding")
    text = (data.text or "").strip()
    if encoding == "csv":
        values = [int(token) for token in text.replace("\n", "").split(",") if token.strip()]
    elif encoding == "base64":
        raw = base64.b64decode(text)
        compression = data.get("compression")
        if compression == "zlib":
            raw = zlib.decompress(raw)
        elif compression == "gzip":
            raw = gzip.decompress(raw)
        elif compression is not None:
            raise TmxError(
                f"couche {layer_name!r} : compression {compression!r} non gérée "
                "(choisissez CSV, ou base64 avec zlib/gzip, dans les propriétés de la carte)"
            )
        values = list(struct.unpack(f"<{len(raw) // 4}I", raw))
    else:
        raise TmxError(f"couche {layer_name!r} : encodage {encoding!r} non géré (utilisez CSV)")
    return tuple(value & _GID_MASK for value in values)
