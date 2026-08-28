"""Tests for the encryption envelope reference implementation.

Spec: specs/encryption-envelope-v0.1.md
"""

import os

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.modules.crypto.envelope import (
    EnvelopeError,
    canonical_json,
    check_sensitivity_propagation,
    ciphertext_hash,
    decrypt_media_chunk,
    decrypt_op_value,
    encrypt_media_chunk,
    encrypt_op_value,
    media_nonce,
    op_nonce,
    unwrap_content_key,
    wrap_content_key,
    wrap_to_recipients,
)
from app.modules.form_engine.runtime import CompiledForm

OP = dict(
    op_id="01J8Z0000000000000000000",
    submission_id="01J8Y0000000000000000000",
    path="members[i3].age",
    form_version=3,
)


def keypair():
    private = X25519PrivateKey.generate()
    return private.private_bytes_raw(), private.public_key().public_bytes_raw()


# -- canonical JSON --------------------------------------------------------


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_canonical_json_has_no_insignificant_whitespace():
    assert canonical_json({"a": [1, 2]}) == b'{"a":[1,2]}'


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json(float("nan"))


# -- nonce derivation ------------------------------------------------------


def test_op_nonce_is_deterministic_and_correct_length():
    assert op_nonce("dev_a", 1) == op_nonce("dev_a", 1)
    assert len(op_nonce("dev_a", 1)) == 12


def test_op_nonce_differs_across_devices_and_counters():
    assert op_nonce("dev_a", 1) != op_nonce("dev_b", 1)
    assert op_nonce("dev_a", 1) != op_nonce("dev_a", 2)


def test_op_nonce_never_repeats_over_a_long_counter_run():
    """Nonce reuse is catastrophic for AES-GCM; prove derivation does not collide."""
    seen = {op_nonce("dev_a", i) for i in range(20_000)}
    assert len(seen) == 20_000


def test_media_nonce_is_deterministic_per_chunk():
    assert media_nonce("m1", 0) != media_nonce("m1", 1)
    assert media_nonce("m1", 0) == media_nonce("m1", 0)


# -- key wrapping ----------------------------------------------------------


def test_wrap_and_unwrap_round_trip():
    private, public = keypair()
    content_key = os.urandom(32)
    wrapped = wrap_content_key(content_key, "ck1", public, "pk1")
    assert unwrap_content_key(wrapped, private) == content_key


def test_wrong_private_key_cannot_unwrap():
    _, public = keypair()
    other_private, _ = keypair()
    wrapped = wrap_content_key(os.urandom(32), "ck1", public, "pk1")
    with pytest.raises(EnvelopeError):
        unwrap_content_key(wrapped, other_private)


def test_wrap_is_bound_to_its_recipient_and_content_key():
    """A wrap must not be transplantable between recipients or submissions."""
    private, public = keypair()
    wrapped = wrap_content_key(os.urandom(32), "ck1", public, "pk1")
    forged = type(wrapped)(
        project_key_id="pk2",  # claim a different recipient
        content_key_id=wrapped.content_key_id,
        ephemeral_public=wrapped.ephemeral_public,
        nonce=wrapped.nonce,
        wrapped_key=wrapped.wrapped_key,
    )
    with pytest.raises(EnvelopeError):
        unwrap_content_key(forged, private)


def test_multi_recipient_wrapping_any_key_opens_it():
    """Lost-key recovery: a backup holder can open the same content key."""
    lead_private, lead_public = keypair()
    backup_private, backup_public = keypair()
    recovery_private, recovery_public = keypair()

    content_key = os.urandom(32)
    wraps = wrap_to_recipients(
        content_key,
        "ck1",
        {"pk_lead": lead_public, "pk_backup": backup_public, "pk_recovery": recovery_public},
    )
    assert len(wraps) == 3

    by_key = {w.project_key_id: w for w in wraps}
    assert unwrap_content_key(by_key["pk_lead"], lead_private) == content_key
    assert unwrap_content_key(by_key["pk_backup"], backup_private) == content_key
    assert unwrap_content_key(by_key["pk_recovery"], recovery_private) == content_key


def test_wrap_requires_at_least_one_recipient():
    with pytest.raises(EnvelopeError):
        wrap_to_recipients(os.urandom(32), "ck1", {})


# -- operation values ------------------------------------------------------


def test_op_value_round_trip():
    key = os.urandom(32)
    ciphertext, nonce = encrypt_op_value(
        34, key, device_id="dev_a", counter=148, **OP
    )
    assert decrypt_op_value(ciphertext, nonce, key, **OP) == 34


@pytest.mark.parametrize(
    "value",
    [None, 0, -1, 3.5, "", "نص عربي", True, [1, 2, 3], {"lat": 24.7, "lon": 46.6}],
)
def test_op_value_round_trip_for_every_value_shape(value):
    key = os.urandom(32)
    ciphertext, nonce = encrypt_op_value(
        value, key, device_id="dev_a", counter=1, **OP
    )
    assert decrypt_op_value(ciphertext, nonce, key, **OP) == value


def test_ciphertext_cannot_be_moved_to_another_field():
    """The core AAD guarantee: relocating an answer must fail loudly."""
    key = os.urandom(32)
    ciphertext, nonce = encrypt_op_value(
        95000, key, device_id="dev_a", counter=1, **{**OP, "path": "income"}
    )
    with pytest.raises(EnvelopeError):
        decrypt_op_value(ciphertext, nonce, key, **{**OP, "path": "age"})


def test_ciphertext_cannot_be_replayed_against_another_form_version():
    key = os.urandom(32)
    ciphertext, nonce = encrypt_op_value(
        34, key, device_id="dev_a", counter=1, **OP
    )
    with pytest.raises(EnvelopeError):
        decrypt_op_value(ciphertext, nonce, key, **{**OP, "form_version": 4})


def test_tampered_ciphertext_is_rejected():
    key = os.urandom(32)
    ciphertext, nonce = encrypt_op_value(34, key, device_id="dev_a", counter=1, **OP)
    tampered = bytes([ciphertext[0] ^ 0x01]) + ciphertext[1:]
    with pytest.raises(EnvelopeError):
        decrypt_op_value(tampered, nonce, key, **OP)


def test_two_devices_produce_independent_ciphertext_for_the_same_answer():
    """Each device has its own content key, so identical answers do not
    produce identical ciphertext the server could correlate."""
    a_ct, _ = encrypt_op_value(34, os.urandom(32), device_id="dev_a", counter=1, **OP)
    b_ct, _ = encrypt_op_value(34, os.urandom(32), device_id="dev_b", counter=1, **OP)
    assert a_ct != b_ct


# -- media -----------------------------------------------------------------


def test_media_chunk_round_trip():
    key = os.urandom(32)
    chunk = os.urandom(4096)
    ciphertext, _ = encrypt_media_chunk(chunk, key, media_id="m1", chunk_index=0)
    assert decrypt_media_chunk(ciphertext, key, media_id="m1", chunk_index=0) == chunk


def test_media_chunk_cannot_be_reordered():
    key = os.urandom(32)
    ciphertext, _ = encrypt_media_chunk(b"first", key, media_id="m1", chunk_index=0)
    with pytest.raises(EnvelopeError):
        decrypt_media_chunk(ciphertext, key, media_id="m1", chunk_index=1)


def test_identical_files_do_not_share_a_ciphertext_hash():
    """Hashing ciphertext, not plaintext, stops the server confirming that two
    submissions contain the same photograph."""
    plaintext = b"same photo bytes"
    a, _ = encrypt_media_chunk(plaintext, os.urandom(32), media_id="m1", chunk_index=0)
    b, _ = encrypt_media_chunk(plaintext, os.urandom(32), media_id="m2", chunk_index=0)
    assert ciphertext_hash([a]) != ciphertext_hash([b])


# -- sensitivity propagation ----------------------------------------------


def _form(children):
    return {
        "irVersion": "0.1",
        "formId": "sens",
        "version": 1,
        "title": {"en": "sens"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": children,
    }


def test_calculation_reading_a_sensitive_field_must_be_sensitive():
    form = CompiledForm(
        _form(
            [
                {"type": "question", "id": "hiv_status", "dataType": "text",
                 "label": {"en": "x"}, "sensitive": True},
                {"type": "question", "id": "summary", "dataType": "boolean",
                 "label": {"en": "y"},
                 "calculate": {"op": "eq", "args": [
                     {"op": "ref", "path": "hiv_status"},
                     {"op": "lit", "value": "positive"}]}},
            ]
        )
    )
    violations = check_sensitivity_propagation(form)
    assert len(violations) == 1
    assert "summary" in violations[0]


def test_no_violation_when_the_derived_field_is_also_sensitive():
    form = CompiledForm(
        _form(
            [
                {"type": "question", "id": "hiv_status", "dataType": "text",
                 "label": {"en": "x"}, "sensitive": True},
                {"type": "question", "id": "summary", "dataType": "boolean",
                 "label": {"en": "y"}, "sensitive": True,
                 "calculate": {"op": "eq", "args": [
                     {"op": "ref", "path": "hiv_status"},
                     {"op": "lit", "value": "positive"}]}},
            ]
        )
    )
    assert check_sensitivity_propagation(form) == []
