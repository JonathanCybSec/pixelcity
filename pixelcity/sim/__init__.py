"""Noyau de la simulation : aucun import de pygame n'est autorisé ici.

Ce fichier reste volontairement vide. Si on y importait `Simulation`, le simple
fait d'écrire `from pixelcity.sim.types import ...` (ce que font `world/` et
`agents/`) chargerait `simulation.py`, qui importe lui-même `world/` et
`agents/` : un import circulaire. Les `__init__.py` minces évitent ce piège.
"""
