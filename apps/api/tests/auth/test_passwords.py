from app.security.passwords import PasswordHasher, PasswordHashParameters


def test_password_hasher_uses_argon2id_and_redacts_values() -> None:
    hasher = PasswordHasher(
        PasswordHashParameters(
            time_cost=1,
            memory_cost_kib=16_384,
            parallelism=1,
            hash_len=16,
            salt_len=16,
        )
    )
    password = "correct-horse-battery-staple"
    encoded = hasher.hash(password)

    assert encoded.startswith("$argon2id$")
    assert hasher.verify(encoded, password)
    assert not hasher.verify(encoded, "wrong-password")
    assert password not in repr(hasher)
    assert password not in encoded
