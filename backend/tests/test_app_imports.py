"""Guards against an incomplete model registry in the app's own import graph.

Runs in a clean subprocess on purpose: inside the test process, unrelated
tests import every model module as a side effect, which is exactly how the
missing-registry bug stayed invisible until the first real API request.
"""

import subprocess
import sys


def test_app_import_graph_resolves_every_foreign_key() -> None:
    probe = (
        "import app.main\n"
        "from sqlalchemy.sql.ddl import sort_tables\n"
        "from app.infrastructure.database import Base\n"
        "list(sort_tables(Base.metadata.tables.values()))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "importing app.main leaves Base.metadata unresolvable:\n" + result.stderr[-2000:]
    )
