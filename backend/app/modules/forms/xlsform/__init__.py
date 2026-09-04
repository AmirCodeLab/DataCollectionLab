"""XLSForm import.

`IMPORTER_VERSION` is stored with every imported form version. A form imported
before a bug was fixed carries warnings that mean something different from the
same warnings today, and without a version recorded beside them there is no way
to tell those two apart six months later.

Bumped whenever the importer's *output* changes for an unchanged input — a new
supported function, a corrected translation, a changed severity. Not for
refactoring.
"""

IMPORTER_VERSION = "0.1.0"
