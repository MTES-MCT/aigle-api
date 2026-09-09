"""Défi de connexion à second facteur : état éphémère dans le cache.

Le jeton est opaque et n'est pas un JWT, donc JWTAuthentication ne peut
structurellement pas l'accepter sur une route métier (contrairement à un JWT
porteur d'un claim « en attente de 2FA », qui passerait aussi /auth/jwt/verify/).

Ce module est FAIL-CLOSED : une panne du cache refuse la connexion, elle ne la
laisse jamais passer.
"""

import hashlib
import logging
import secrets
from typing import Optional

from django.core.cache import cache

logger = logging.getLogger("aigle")

CHALLENGE_TTL_SECONDS = 10 * 60
QUOTA_WINDOW_SECONDS = 3600
MAX_LINKS_PER_HOUR = 5


class MfaChallengeUnavailable(Exception):
    """Le défi n'a pas pu être créé ou relu : la connexion doit être refusée."""


class MfaChallengeQuotaExceeded(MfaChallengeUnavailable):
    """Trop de liens demandés pour ce compte sur l'heure glissante."""


def _challenge_key(token: str) -> str:
    # Indexé par empreinte : lire le cache ne rend pas un lien rejouable.
    return f"aigle:mfa:link:{hashlib.sha256(token.encode()).hexdigest()}"


def _quota_key(user_id: int) -> str:
    return f"aigle:mfa:sent:{user_id}"


def check_quota(user_id: int) -> None:
    """Refuse un nouveau lien si la fenêtre horaire du compte est épuisée."""
    try:
        sent = cache.get(_quota_key(user_id), 0)
    except Exception as error:
        logger.exception("mfa_challenge: lecture du quota impossible")
        raise MfaChallengeUnavailable() from error

    if sent >= MAX_LINKS_PER_HOUR:
        raise MfaChallengeQuotaExceeded()


def register_sent(user_id: int) -> None:
    """Incrémente le quota, à n'appeler qu'après un envoi réussi.

    Ne lève jamais : à ce stade l'utilisateur détient un lien valide, échouer sur un
    compteur le priverait d'une connexion qui a abouti.
    """
    key = _quota_key(user_id)
    try:
        # add() = SETNX : pose le compteur sans écraser le TTL d'une fenêtre en cours.
        cache.add(key, 0, timeout=QUOTA_WINDOW_SECONDS)
        cache.incr(key)
    except ValueError:
        # La fenêtre a expiré entre add() et incr() : elle repart à zéro, sans effet.
        pass
    except Exception:
        logger.exception("mfa_challenge: incrément du quota impossible")


def create(user_id: int) -> str:
    """Crée un défi et rend le jeton en clair, à ne transmettre que par courriel."""
    token = secrets.token_urlsafe(32)

    try:
        cache.set(_challenge_key(token), user_id, timeout=CHALLENGE_TTL_SECONDS)
    except Exception as error:
        logger.exception("mfa_challenge: création impossible")
        raise MfaChallengeUnavailable() from error

    return token


def consume(token: str) -> Optional[int]:
    """Usage unique strict : seul l'appelant qui supprime réellement la clé l'emporte."""
    key = _challenge_key(token)

    try:
        user_id = cache.get(key)
        if user_id is None:
            return None
        if not cache.delete(key):
            return None
    except Exception as error:
        logger.exception("mfa_challenge: consommation impossible")
        raise MfaChallengeUnavailable() from error

    return user_id
