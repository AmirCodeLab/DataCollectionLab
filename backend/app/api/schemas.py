"""Wire types that belong to no single module: the health probe and the plain
`{"detail": "..."}` refusal every read endpoint uses for "no such thing".

Nothing here is domain logic. It is here because the OpenAPI document is the
contract (docs/project-conventions.md, "The API contract"), and a route whose response FastAPI
has to infer — `dict[str, str]`, `dict[str, Any]` — publishes `additional
Properties` instead of a shape. A generated client then has `Record<string,
unknown>` where the API has fields, which is the same as having no contract for
that route at all.
"""

from pydantic import BaseModel


class Health(BaseModel):
    """The liveness probe.

    The console polls this to tell "the API is down" apart from "the API is up
    and there is no data", which are the same empty screen otherwise.
    """

    status: str
    # Which deployment this is. Several refusals depend on it — a published
    # test keypair is usable in development and nowhere else — so a console
    # showing data from the wrong environment is worth being able to see.
    environment: str


class MessageError(BaseModel):
    """The body of a refusal that carries prose and nothing to branch on.

    `{"detail": "submission not found"}`. Used where there is exactly one way
    to fail and the status code already says which: a 404 on a read endpoint.
    Anything a client must branch on gets a `reason` field instead — see
    `DeviceRegisterError` and `ProjectKeyError` in `modules/projects/schemas.py`.
    """

    detail: str
