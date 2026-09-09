"""Shared FastAPI dependencies.

`get_db` is `app.api.access.get_db`, re-exported: one session per request,
scoped to the request's organisation before anything is read, and to the
person once their cookie resolves. It lives in `access` because who is
asking and what they may see are one decision (ERD §1), and is imported from
here so that every route's `Depends(get_db)` is the same object FastAPI
caches per request.
"""

from app.api.access import get_db

__all__ = ["get_db"]
