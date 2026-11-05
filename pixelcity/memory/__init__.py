"""La mémoire des habitants : flux de souvenirs, récupération, réflexion.

Architecture reprise du papier *Generative Agents* (Park et al., 2023) :
1. le FLUX : tout ce que vit l'habitant est noté, daté, avec une importance ;
2. la RÉCUPÉRATION : avant de parler, on ressort les souvenirs les plus utiles,
   selon trois critères (récence, importance, pertinence) ;
3. la RÉFLEXION : chaque nuit, l'habitant tire de ses souvenirs marquants
   quelques idées plus générales (« je m'entends bien avec Léa »), qui
   deviennent à leur tour des souvenirs.
"""
