"""Verify an Amazon Cognito ID token on the server. The page signs in straight to Cognito (as The Vayu Project does) and sends us the ID token;
we check its signature against the pool's public keys, its issuer, audience, expiry and that Cognito verified the email, and only then
create or find the account here. Without CC_COGNITO_POOL_ID and CC_COGNITO_CLIENT_ID the app uses its own email-and-password accounts instead."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CognitoConfig:
    region: str
    pool_id: str
    client_id: str

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.pool_id}"


def from_env() -> Optional[CognitoConfig]:
    pool, client = os.getenv("CC_COGNITO_POOL_ID", ""), os.getenv("CC_COGNITO_CLIENT_ID", "")
    if not pool or not client:
        return None
    return CognitoConfig(os.getenv("CC_COGNITO_REGION") or os.getenv("AWS_REGION", "us-east-1"), pool, client)


_jwks: dict[str, object] = {}


def verify_id_token(token: str, cfg: CognitoConfig, key_for=None) -> dict:
    """Claims of a valid ID token for this pool and app client; raises ValueError otherwise. `key_for(token)` is injectable for tests."""
    import jwt
    try:
        if key_for is None:
            client = _jwks.get(cfg.issuer)
            if client is None:
                client = _jwks[cfg.issuer] = jwt.PyJWKClient(f"{cfg.issuer}/.well-known/jwks.json", cache_keys=True)
            key = client.get_signing_key_from_jwt(token).key
        else:
            key = key_for(token)
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=cfg.client_id, issuer=cfg.issuer, options={"require": ["exp", "iss", "aud", "sub"]})
    except Exception as e:                       # bad signature, wrong pool, expired, malformed
        raise ValueError(type(e).__name__) from e
    if claims.get("token_use") != "id" or not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise ValueError("not a verified id token")
    return claims
