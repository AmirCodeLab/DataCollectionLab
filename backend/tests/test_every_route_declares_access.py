"""Every route says who may call it, and this is what says so.

The question asked before the routes were written: what would pass every
test? A permission check that is correct on every screen and absent from the
one place nobody thinks of as a screen — an export, a report, a sync
endpoint. The organisation and team boundaries are policies in the database
and cannot be skipped; the *courtesy* check, the one that turns a refusal into
a 401 or 403 a screen can show, is per route and could be. So this walks the
app's route table — not a list somebody maintains — and fails on any route
that declares neither `access(...)` nor `public(...)`, naming it.

A public route carries its reason in the declaration. The set is also pinned
here, because "public" is the exemption, and an exemption that can grow
without a diff is the hole the lint exists to close.
"""

from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute

from app.main import app

#: The routes anyone may call, with the reason the declaration gives. Adding
#: one is a decision: it goes here, with the reason, in the same change.
PUBLIC = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/devices"),
    ("GET", "/health"),
}


def _markers(dependant: Any) -> list[dict[str, Any]]:
    found = [
        dependant.call.__dcp_access__
        for dependant in _walk(dependant)
        if hasattr(dependant.call, "__dcp_access__")
    ]
    return found


def _walk(dependant: Any) -> list[Any]:
    out = [dependant]
    for child in dependant.dependencies:
        out += _walk(child)
    return out


def _api_routes() -> list[Any]:
    """Every operation the app serves, with its full path and its dependant.

    FastAPI keeps an included router as a lazy `_IncludedRouter` in
    `app.routes`; its `effective_route_contexts` are the operations with the
    prefix applied. Walked rather than assumed flat, so a router added inside a
    router is still seen.
    """
    found: list[Any] = []

    def visit(node: Any) -> None:
        if isinstance(node, APIRoute):
            found.append(node)
        elif hasattr(node, "effective_route_contexts"):
            found.extend(node.effective_route_contexts())
        elif hasattr(node, "routes"):
            for child in node.routes:
                visit(child)

    for route in app.routes:
        visit(route)
    return found


def test_every_route_declares_who_may_call_it() -> None:
    undeclared = []
    for route in _api_routes():
        if route.path == "/health":
            continue  # liveness, no database, declared below by being pinned
        markers = _markers(route.dependant)
        if not markers:
            for method in sorted(route.methods):
                undeclared.append(f"{method} {route.path}")
    assert undeclared == [], (
        "routes that declare neither access(...) nor public(...):\n  "
        + "\n  ".join(undeclared)
        + "\n\nA route without a declaration is the export nobody thought of. Add "
        "dependencies=[Depends(access(permission=..., app=...))] or a parameter that "
        "depends on it, or public('why') with the reason (app/api/access.py)."
    )


def test_the_public_routes_are_exactly_the_pinned_ones() -> None:
    public = set()
    for route in _api_routes():
        for marker in _markers(route.dependant):
            if "public" in marker:
                assert marker["public"].strip(), f"{route.path} is public with no reason"
                for method in route.methods:
                    public.add((method, route.path))
    public.add(("GET", "/health"))
    assert public == PUBLIC, (
        f"public routes changed: now {sorted(public)}, pinned {sorted(PUBLIC)}. "
        "If that is deliberate, the pinned set changes in the same commit, with the reason."
    )


def test_a_route_declares_at_most_one_way() -> None:
    """Two declarations on one route is a route whose meaning depends on
    which one runs first."""
    doubled = [
        f"{sorted(route.methods)} {route.path}: {len(_markers(route.dependant))} declarations"
        for route in _api_routes()
        if len(_markers(route.dependant)) > 1
    ]
    assert doubled == [], "\n".join(doubled)
