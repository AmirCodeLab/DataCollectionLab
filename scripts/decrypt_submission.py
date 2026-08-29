#!/usr/bin/env python3
"""TEST ONLY — read one encrypted submission back, with a private key file.

    python scripts/decrypt_submission.py 01M1787YVJ5WKGESA0PQPT1R6W --test-key primary
    python scripts/decrypt_submission.py 01SUB... --key ~/Downloads/dcp-dev-primary-key.json
    python scripts/decrypt_submission.py 01SUB... --key key.json --ops --json

This is the developer-side half of encryption envelope §7. The product-side half
is the console's decryption panel (web/src/pages/SubmissionPage.tsx), which does
exactly the same thing in the browser with a key that never touches disk. This
script exists because a terminal is where you check whether encrypted data is
still readable, and because "the ciphertext is stored correctly" is not the same
claim as "the answers can be recovered".

TEST ONLY for one specific reason: it takes a private key off disk and prints
plaintext answers to a terminal, where they land in scrollback, in `script`
logs, and in whatever is recording the session. That is fine for development
data and wrong for real respondent data. Nothing here uploads or writes a key
anywhere.

What it does, in order (§7):

1. fetch the op log, the wrapped content keys, and the project's recipient list;
2. work out which recipient this private key is;
3. unwrap every content key wrapped to it — a submission built by several
   devices has one per device (§4.2), and needs all of them;
4. decrypt each encrypted op value, authenticating it against the AAD that
   binds it to its op id, submission, path and form version (§5);
5. fold the log in (counter, deviceId) order, exactly as the server and the
   clients do, and print the answers.

A content key it cannot open is reported, not skipped silently: that is the
rotation case (§8), where a key added after the fact opens nothing older, and
the difference between "no answers" and "no answers you hold the key for" is
the difference between a bug and a key custody problem.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))


def _reexec_in_backend_venv() -> None:
    """Re-run under backend/.venv when the current interpreter lacks the deps.

    Only `cryptography` is needed — this talks to the API over HTTP and never
    opens the database, so it can be pointed at any deployment.
    """
    try:
        import cryptography  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        return

    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"
    already_tried = os.environ.get("DCP_DECRYPT_REEXEC") == "1"
    if already_tried or not venv_python.exists() or Path(sys.executable) == venv_python:
        sys.exit(
            "Cannot import cryptography, and no usable backend/.venv to fall back on.\n"
            "    cd backend && pip install -e '.[dev]'"
        )
    os.execve(
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        {**os.environ, "DCP_DECRYPT_REEXEC": "1"},
    )


_reexec_in_backend_venv()

from app.modules.crypto.envelope import (  # noqa: E402
    EnvelopeError,
    WrappedKey,
    decrypt_op_value,
    unwrap_content_key,
)

DEFAULT_API = "http://localhost:8000"

BANNER = """\
TEST ONLY — this prints decrypted answers to your terminal, where they stay in
scrollback and in any session recording. Development data only.
"""


# ---------------------------------------------------------------------------
# The API, read-only
# ---------------------------------------------------------------------------


def _get(api: str, path: str) -> Any:
    url = f"{api.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:400]
        sys.exit(f"GET {url} failed: {error.code} {error.reason}\n{body}")
    except urllib.error.URLError as error:
        sys.exit(f"GET {url} failed: {error.reason}\nIs the API running at {api}?")


# ---------------------------------------------------------------------------
# The private key
# ---------------------------------------------------------------------------


def _load_private_key(path: Path) -> bytes:
    """Accept the console's downloaded key file, or a bare hex scalar.

    The console writes a JSON file with a `privateKey` field (see
    web/src/lib/projectKey.ts); a key generated elsewhere is usually just 64 hex
    characters in a file. Both are read the same way, and neither is echoed.
    """
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        sys.exit(f"Cannot read {path}: {error}")

    scalar = raw
    if raw.startswith("{"):
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as error:
            sys.exit(f"{path} looks like JSON but does not parse: {error}")
        value = document.get("privateKey")
        if not isinstance(value, str):
            sys.exit(
                f"{path} has no string `privateKey` field. Expected the file the "
                "console downloaded when the keypair was generated."
            )
        scalar = value

    scalar = "".join(scalar.split()).lower()
    try:
        material = bytes.fromhex(scalar)
    except ValueError:
        sys.exit(f"{path} does not contain a hex private key.")
    if len(material) != 32:
        sys.exit(f"A private key is 32 bytes; {path} holds {len(material)}.")
    return material


def _test_only_private_key(role: str, api: str) -> bytes:
    """The fixed development scalars, and only against a development server.

    The private halves are in scripts/dev_project_key.py and therefore in
    version control. Refusing to use them against anything but a development
    API is the same rule the server applies from its side
    (app/modules/crypto/published_test_keys.py) — pointed the other way, at the
    person about to type it.
    """
    health = _get(api, "/health")
    environment = health.get("environment")
    if environment != "development":
        sys.exit(
            f"Refusing --test-key against {api}: it reports environment "
            f"{environment!r}, not 'development'. These private keys are "
            "published in the repository; if real data is wrapped to one, that "
            "data is already compromised and this script is not the fix."
        )

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dev_project_key import TEST_ONLY_PRIVATE_KEYS

    return bytes.fromhex(TEST_ONLY_PRIVATE_KEYS[role])


def _public_hex(private_key: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    return (
        X25519PrivateKey.from_private_bytes(private_key)
        .public_key()
        .public_bytes_raw()
        .hex()
    )


# ---------------------------------------------------------------------------
# Envelope §7
# ---------------------------------------------------------------------------


def _unwrap_content_keys(
    keys_response: dict[str, Any],
    project_keys: dict[str, dict[str, Any]],
    private_key: bytes,
    our_key_ids: set[str],
) -> tuple[dict[str, bytes], list[str]]:
    """{contentKeyId: material} plus a line per content key we cannot open.

    Every wrap is tried, not only the ones addressed to a key id we matched:
    the id match is a convenience for reporting, and a private key that opens a
    wrap is the only evidence that actually counts.
    """
    opened: dict[str, bytes] = {}
    problems: list[str] = []

    for content_key in keys_response["contentKeys"]:
        key_id = content_key["contentKeyId"]
        for wrap in content_key["wraps"]:
            try:
                opened[key_id] = unwrap_content_key(
                    WrappedKey(
                        project_key_id=wrap["projectKeyId"],
                        content_key_id=key_id,
                        ephemeral_public=bytes.fromhex(wrap["ephemeralPublic"]),
                        nonce=bytes.fromhex(wrap["nonce"]),
                        wrapped_key=bytes.fromhex(wrap["wrappedKey"]),
                    ),
                    private_key,
                )
                break
            except EnvelopeError:
                # A wrap addressed to another recipient. Expected: every content
                # key carries one wrap per recipient and we are only one of them.
                continue
        else:
            addressed = ", ".join(
                _describe_project_key(wrap["projectKeyId"], project_keys)
                for wrap in content_key["wraps"]
            )
            problems.append(
                f"content key {key_id} (device {content_key['deviceId']}) is not "
                f"wrapped to this private key. It is wrapped to: {addressed}."
                + (
                    ""
                    if not our_key_ids
                    else " This key was registered after those wraps were made; "
                    "historical submissions are never re-wrapped (envelope §8)."
                )
            )

    return opened, problems


def _describe_project_key(key_id: str, project_keys: dict[str, dict[str, Any]]) -> str:
    key = project_keys.get(key_id)
    if key is None:
        return f"{key_id} (unknown to this project)"
    revoked = " REVOKED" if key.get("revokedAt") else ""
    return f"{key_id} ({key['role']}, {key['label']!r}{revoked})"


def _decrypt_ops(
    detail: dict[str, Any], content_keys: dict[str, bytes]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Fold the log, decrypting as it goes. Returns (answers, rows, problems).

    The fold is the one in sync protocol §6 and in the server's own
    `_fold_submission`: last writer wins, ordered by (counter, deviceId), never
    by wall clock. Reimplementing it differently here would produce a plausible
    set of answers that disagrees with every other view of the same submission.
    """
    answers: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    for op in sorted(detail["ops"], key=lambda o: (o["counter"], o["deviceId"])):
        value: Any = op["value"]
        state = "plaintext"

        if op["encrypted"]:
            material = content_keys.get(op["contentKeyId"])
            if material is None:
                state = "no key"
                problems.append(
                    f"op {op['id']} ({op['path']}) needs content key "
                    f"{op['contentKeyId']}, which this private key does not open."
                )
            else:
                try:
                    value = decrypt_op_value(
                        bytes.fromhex(op["valueCiphertext"]),
                        bytes.fromhex(op["nonce"]),
                        material,
                        op_id=op["id"],
                        submission_id=detail["id"],
                        path=op["path"] or "",
                        form_version=detail["formVersion"],
                    )
                    state = "decrypted"
                except EnvelopeError as error:
                    # Authentication failure is never noise. It means these bytes
                    # are not the ones that were sealed for this op at this path
                    # in this form version — corruption, or tampering.
                    state = "FAILED"
                    problems.append(f"op {op['id']} ({op['path']}) did not authenticate: {error}")

        rows.append({**op, "plainValue": value, "state": state})

        if state in ("FAILED", "no key"):
            continue
        path = op["path"]
        if op["kind"] == "set" and path is not None:
            answers[path] = value
        elif op["kind"] == "unset" and path is not None:
            answers.pop(path, None)
        elif op["kind"] == "repeat_delete" and path is not None:
            dot, bracket = path + ".", path + "["
            answers = {
                k: v
                for k, v in answers.items()
                if k != path and not k.startswith(dot) and not k.startswith(bracket)
            }

    return answers, rows, problems


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _report(
    detail: dict[str, Any],
    keys_response: dict[str, Any],
    project_keys: dict[str, dict[str, Any]],
    our_key_ids: set[str],
    our_public: str,
    opened: dict[str, bytes],
    answers: dict[str, Any],
    rows: list[dict[str, Any]],
    problems: list[str],
    show_ops: bool,
) -> None:
    print(f"Submission {detail['id']}")
    print(f"  form      {detail['formTitle']} ({detail['formId']} v{detail['formVersion']})")
    print(f"  project   {detail['projectId']}")
    print(f"  status    {detail['status']}   ops {detail['opCount']}")
    if detail.get("opsTruncated"):
        print(
            f"  WARNING   only the first {len(detail['ops'])} ops were returned; "
            "the answers below are a prefix of the log, not the whole of it."
        )

    print(f"\nPrivate key public half: {our_public}")
    if our_key_ids:
        for key_id in sorted(our_key_ids):
            print(f"  recipient {_describe_project_key(key_id, project_keys)}")
    else:
        print(
            "  This public key is not registered as a recipient of this project. "
            "Any content key it opens was wrapped to it before it was removed, "
            "or under another project."
        )

    print(f"\nContent keys ({len(keys_response['contentKeys'])}):")
    for content_key in keys_response["contentKeys"]:
        key_id = content_key["contentKeyId"]
        mark = "opened" if key_id in opened else "CLOSED"
        print(
            f"  {mark:>7}  {key_id}  device {content_key['deviceId']}  "
            f"{len(content_key['wraps'])} wraps"
        )

    print(f"\nAnswers ({len(answers)}):")
    if not answers:
        print("  (none)")
    for path in sorted(answers):
        print(f"  {path:<28} {json.dumps(answers[path], ensure_ascii=False)}")

    if show_ops:
        print("\nOps, in (counter, deviceId) order:")
        for row in rows:
            rendered = (
                "—"
                if row["state"] in ("FAILED", "no key")
                else json.dumps(row["plainValue"], ensure_ascii=False)
            )
            print(
                f"  {row['counter']:>6}  {row['deviceId']:<24} {row['kind']:<14}"
                f"{str(row['path']):<28} {row['state']:<10} {rendered}"
            )

    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TEST ONLY: decrypt one submission with a private key file.",
        epilog="The private key is read from disk and never sent anywhere.",
    )
    parser.add_argument("submission_id", help="the submission to decrypt")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--key",
        type=Path,
        help="private key file: the console's downloaded JSON, or a bare hex scalar",
    )
    source.add_argument(
        "--test-key",
        choices=("primary", "backup", "recovery"),
        help="use a fixed key from scripts/dev_project_key.py (development servers only)",
    )
    parser.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    parser.add_argument("--ops", action="store_true", help="print the op log as well")
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="print the folded answers as JSON and nothing else",
    )
    args = parser.parse_args()

    if not args.as_json:
        print(BANNER)

    private_key = (
        _test_only_private_key(args.test_key, args.api)
        if args.test_key
        else _load_private_key(args.key)
    )
    our_public = _public_hex(private_key)

    submission = args.submission_id
    detail = _get(args.api, f"/api/v1/submissions/{submission}")
    keys_response = _get(args.api, f"/api/v1/submissions/{submission}/keys")
    # Revoked keys included deliberately: a wrap made before revocation is still
    # a wrap, and naming the recipient is how the rotation story stays legible.
    listed = _get(
        args.api, f"/api/v1/projects/{detail['projectId']}/keys?includeRevoked=true"
    )
    project_keys = {key["keyId"]: key for key in listed["keys"]}
    our_key_ids = {
        key["keyId"] for key in listed["keys"] if key["publicKey"] == our_public
    }

    opened, key_problems = _unwrap_content_keys(
        keys_response, project_keys, private_key, our_key_ids
    )
    answers, rows, op_problems = _decrypt_ops(detail, opened)
    problems = key_problems + op_problems

    if args.as_json:
        print(json.dumps(answers, ensure_ascii=False, indent=2, sort_keys=True))
        for problem in problems:
            print(f"warning: {problem}", file=sys.stderr)
    else:
        _report(
            detail,
            keys_response,
            project_keys,
            our_key_ids,
            our_public,
            opened,
            answers,
            rows,
            problems,
            args.ops,
        )

    # Non-zero when something did not come back, so a script wrapping this one
    # cannot mistake a partial recovery for a whole one.
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
