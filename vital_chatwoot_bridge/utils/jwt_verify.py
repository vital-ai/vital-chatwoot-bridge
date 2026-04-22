"""
JWT token verification for inbound requests.
Verifies Keycloak-issued JWTs using JWKS (JSON Web Key Set) endpoint.

This is complementary to jwt_auth.py which *obtains* tokens (as a client).
This module *verifies* incoming tokens (as a resource server).
"""

import logging
import time
from typing import Optional, Dict, Any

import httpx
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from vital_chatwoot_bridge.core.config import get_settings
from vital_chatwoot_bridge.core.auth_models import AuthenticatedUser

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for FastAPI
bearer_scheme = HTTPBearer(auto_error=True)

# JWKS cache
_jwks_cache: Optional[Dict[str, Any]] = None
_jwks_cache_time: float = 0
JWKS_CACHE_TTL_SECONDS = 300  # 5 minutes


async def _get_jwks() -> Dict[str, Any]:
    """Fetch and cache JWKS from Keycloak."""
    global _jwks_cache, _jwks_cache_time

    if _jwks_cache and (time.time() - _jwks_cache_time) < JWKS_CACHE_TTL_SECONDS:
        return _jwks_cache

    settings = get_settings()
    jwks_url = (
        f"{settings.keycloak_base_url.rstrip('/')}"
        f"/realms/{settings.keycloak_realm}"
        f"/protocol/openid-connect/certs"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = time.time()
            logger.info(f"🔑 JWKS: Fetched {len(_jwks_cache.get('keys', []))} keys from {jwks_url}")
            return _jwks_cache
    except Exception as e:
        logger.error(f"🔑 JWKS: Failed to fetch JWKS from {jwks_url}: {e}")
        if _jwks_cache:
            logger.warning("🔑 JWKS: Using stale cached JWKS")
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify tokens: JWKS unavailable"
        )


def _extract_roles(claims: Dict[str, Any], client_id: str) -> list:
    """Extract roles from Keycloak JWT claims."""
    roles = []
    # Realm roles
    realm_access = claims.get("realm_access", {})
    roles.extend(realm_access.get("roles", []))
    # Client-specific roles
    resource_access = claims.get("resource_access", {})
    client_roles = resource_access.get(client_id, {})
    roles.extend(client_roles.get("roles", []))
    return roles


def _extract_groups(claims: Dict[str, Any]) -> list:
    """Extract groups from Keycloak JWT claims."""
    return claims.get("groups", [])


def _extract_scopes(claims: Dict[str, Any]) -> list:
    """Extract scopes from JWT claims."""
    scope_str = claims.get("scope", "")
    return scope_str.split() if scope_str else []


async def verify_token(token: str) -> AuthenticatedUser:
    """
    Verify a JWT token and return an AuthenticatedUser.

    Raises HTTPException on any verification failure.
    """
    settings = get_settings()
    jwks_data = await _get_jwks()

    try:
        # Build JWKS client for PyJWT
        jwks_client = pyjwt.PyJWKClient.__new__(pyjwt.PyJWKClient)
        # Manually set the cached keys
        from jwt.api_jwk import PyJWKSet
        jwk_set = PyJWKSet.from_dict(jwks_data)

        # Get the unverified header to find the key
        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID (kid)"
            )

        # Find the matching key
        signing_key = None
        for key in jwk_set.keys:
            if key.key_id == kid:
                signing_key = key
                break

        if not signing_key:
            # Key not found — refresh JWKS cache and retry
            global _jwks_cache_time
            _jwks_cache_time = 0
            jwks_data = await _get_jwks()
            jwk_set = PyJWKSet.from_dict(jwks_data)
            for key in jwk_set.keys:
                if key.key_id == kid:
                    signing_key = key
                    break

        if not signing_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signing key not found in JWKS"
            )

        # Decode and verify the token
        issuer = (
            f"{settings.keycloak_base_url.rstrip('/')}"
            f"/realms/{settings.keycloak_realm}"
        )

        claims = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": False,
            }
        )

        # Verify authorized party (azp) against the allow-list.
        # Keycloak password-grant tokens set aud="account", not the client_id,
        # so we check azp instead of aud.
        token_azp = claims.get("azp", "")
        allowed_azps = settings.keycloak_allowed_azps or [settings.keycloak_client_id]
        if token_azp not in allowed_azps:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token authorized party mismatch: expected one of {allowed_azps}, got {token_azp}",
            )

        # Map claims to AuthenticatedUser
        from datetime import datetime, timezone
        user = AuthenticatedUser(
            client_id=claims.get("azp", settings.keycloak_client_id),
            subject=claims.get("sub", ""),
            scopes=_extract_scopes(claims),
            roles=_extract_roles(claims, settings.keycloak_client_id),
            groups=_extract_groups(claims),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
            issued_at=datetime.fromtimestamp(claims["iat"], tz=timezone.utc),
            username=claims.get("preferred_username"),
            email=claims.get("email"),
            raw_claims=claims,
        )

        logger.debug(f"🔑 JWT: Verified token for user={user.username} sub={user.subject}")
        return user

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except pyjwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token audience mismatch"
        )
    except pyjwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token issuer mismatch"
        )
    except pyjwt.PyJWTError as e:
        logger.error(f"🔑 JWT: Verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔑 JWT: Unexpected error during verification: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """
    FastAPI dependency that extracts and verifies the JWT bearer token.

    Usage:
        @router.get("/protected")
        async def protected_route(user: AuthenticatedUser = Depends(get_current_user)):
            ...
    """
    return await verify_token(credentials.credentials)
