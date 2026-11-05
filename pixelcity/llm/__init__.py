"""Les conversations des habitants : génération par un LLM local (Ollama) ou par script.

Ce paquet ne connaît ni pygame ni la boucle de simulation : il reçoit une
« photo » figée de la situation (`ConversationRequest`) et rend des répliques
(`ConversationResult`). La simulation reste maîtresse du monde.
"""
