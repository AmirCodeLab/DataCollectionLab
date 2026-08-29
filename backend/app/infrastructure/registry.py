"""Imports every module's models so Base.metadata is complete at runtime.

SQLAlchemy resolves inter-module foreign keys (e.g. submission.visit_id ->
visit.id) lazily, at first flush — and it can only resolve tables whose model
module has been imported. Alembic's env.py carries this same import block for
autogenerate; the app process needs it too, otherwise the first insert that
touches a cross-module FK dies with NoReferencedTableError. The test suite
never sees that failure because unrelated tests import the missing modules as
a side effect, so this is enforced by tests/test_app_imports.py in a clean
subprocess.
"""

from app.modules.audit import models as _audit_models  # noqa: F401
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.cases import models as _cases_models  # noqa: F401
from app.modules.crypto import models as _crypto_models  # noqa: F401
from app.modules.entities import models as _entities_models  # noqa: F401
from app.modules.forms import models as _forms_models  # noqa: F401
from app.modules.media import models as _media_models  # noqa: F401
from app.modules.projects import models as _projects_models  # noqa: F401
from app.modules.quality import models as _quality_models  # noqa: F401
from app.modules.submissions import models as _submissions_models  # noqa: F401
from app.modules.sync import models as _sync_models  # noqa: F401
from app.modules.workflows import models as _workflows_models  # noqa: F401
