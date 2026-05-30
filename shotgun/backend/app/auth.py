"""
Shotgun — Firebase Authentication (server-side).

Verifies Firebase ID tokens minted by the Next.js client after Google
sign-in. Every authenticated API call passes the token as
``Authorization: Bearer <id_token>``; this module turns it into a
``FirebaseUser`` (uid + email) and rejects anything invalid.

Initialization:
    On first use we load the service account from either
    FIREBASE_SERVICE_ACCOUNT_FILE (absolute path to JSON) or
    FIREBASE_SERVICE_ACCOUNT_JSON (one-line escaped blob). The latter
    is preferred for cloud deploys; the former for local dev.

Use it on a route:
    @router.get("/me", dependencies=[Depends(require_user)])
    async def me(user: FirebaseUser = Depends(current_user)):
        return {"uid": user.uid, "email": user.email}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)

_admin = None  # lazy-initialized firebase_admin App


@dataclass(frozen=True)
class FirebaseUser:
    """A verified Firebase identity. Equivalent to one row in `users`."""
    uid: str
    email: str | None
    name: str | None = None
    picture: str | None = None
    email_verified: bool = False

    @property
    def is_admin(self) -> bool:
        """True iff the user's email is in ADMIN_EMAILS.

        Admins skip the GitHub App onboarding and get the existing
        DEMO_REPO_FULL_NAME pre-monitored against their local Kiro
        Desktop loop — useful for showing the product without a real
        GitHub App being registered yet.
        """
        if not self.email:
            return False
        return self.email.lower() in settings.admin_emails_list


# ── Admin SDK init ───────────────────────────────────


def _init_admin() -> object:
    """Initialize firebase_admin once, return the App instance.

    Tolerant of missing config — returns None and the API simply rejects
    every auth attempt with 503. That way an unconfigured backend still
    boots so you can build the rest of the platform.
    """
    global _admin
    if _admin is not None:
        return _admin

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.error("auth: firebase_admin not installed")
        return None

    cred = None
    if settings.FIREBASE_SERVICE_ACCOUNT_FILE:
        try:
            cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_FILE)
        except Exception as exc:
            logger.error("auth: bad service-account file — %s", exc)
            return None
    elif settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        try:
            info = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
            cred = credentials.Certificate(info)
        except Exception as exc:
            logger.error("auth: bad service-account JSON — %s", exc)
            return None
    else:
        logger.warning("auth: no Firebase credentials configured")
        return None

    try:
        _admin = firebase_admin.initialize_app(
            cred, {"projectId": settings.FIREBASE_PROJECT_ID}
        )
        logger.info("auth: firebase_admin initialized (project=%s)", settings.FIREBASE_PROJECT_ID)
    except ValueError:
        # Already initialized — fetch the default app.
        _admin = firebase_admin.get_app()
    return _admin


# ── FastAPI dependency ───────────────────────────────


async def current_user(request: Request) -> FirebaseUser | None:
    """Resolve the Firebase user from the Authorization header, if any.

    Returns None when no token is present so routes can opt-in to
    authentication via ``require_user``. Returns a ``FirebaseUser`` when
    the token verifies. Raises 401 on a malformed-or-expired token.
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None

    app = _init_admin()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase not configured on the server",
        )

    from firebase_admin import auth as fb_auth

    try:
        claims = fb_auth.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Firebase token: {exc}",
        )

    return FirebaseUser(
        uid=claims["uid"],
        email=claims.get("email"),
        name=claims.get("name"),
        picture=claims.get("picture"),
        email_verified=bool(claims.get("email_verified")),
    )


def require_user(user: FirebaseUser | None = Depends(current_user)) -> FirebaseUser:
    """Use as a route dependency: rejects unauthenticated requests with 401."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user
