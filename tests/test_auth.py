"""src/auth.py: which Supabase access tokens count as a signed-in user (and every way one must not)."""

import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from src import auth, rate_limit

URL = auth.DEFAULT_SUPABASE_URL
USER = "0f0e0d0c-0b0a-4908-8706-050403020100"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def claims(**override) -> dict:
    now = int(time.time())
    return {"sub": USER, "aud": "authenticated", "role": "authenticated", "iss": f"{URL}/auth/v1",
            "iat": now, "exp": now + 3600, **override}


def token(key=KEY, alg="ES256", **override) -> str:
    return "Bearer " + jwt.encode(claims(**override), key, algorithm=alg, headers={"kid": "test"})


class FakeSigningKey:
    key = KEY.public_key()


class AuthTests(unittest.TestCase):
    def setUp(self):
        jwks = patch.object(auth, "_jwks")
        self.jwks = jwks.start()
        self.jwks.return_value.get_signing_key_from_jwt.return_value = FakeSigningKey()
        self.addCleanup(jwks.stop)
        setting = patch.object(auth.settings, "get_setting", return_value=None)
        setting.start()
        self.addCleanup(setting.stop)

    def test_a_valid_token_is_the_user(self):
        self.assertEqual(auth.user_id(token()), USER)
        self.jwks.assert_called_with(URL)

    def test_tokens_that_must_not_count(self):
        now = int(time.time())
        cases = {
            "no header": None,
            "not bearer": token().replace("Bearer ", "Basic "),
            "garbage": "Bearer not.a.token",
            "signed by another key": token(key=OTHER_KEY),
            "expired": token(exp=now - 120),
            "other audience": token(aud="anon"),
            "anon role": token(role="anon"),
            "other project": token(iss="https://evil.supabase.co/auth/v1"),
            "no user id": token(sub=None),
            "user id not a uuid": token(sub="../admin"),
        }
        for name, header in cases.items():
            with self.subTest(name):
                self.assertIsNone(auth.user_id(header))

    def test_no_algorithm_confusion(self):
        # alg none: no signature at all.
        unsigned = jwt.encode(claims(), None, algorithm="none")
        self.assertIsNone(auth.user_id(f"Bearer {unsigned}"))
        # HS256 signed with the public key's bytes (the classic confusion attack), built by hand as an
        # attacker would (PyJWT itself refuses to sign it): refused before any key lookup.
        public_pem = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        part = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()  # noqa: E731
        signing_input = f"{part({'alg': 'HS256', 'typ': 'JWT', 'kid': 'test'})}.{part(claims())}"
        signature = base64.urlsafe_b64encode(hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        self.assertIsNone(auth.user_id(f"Bearer {signing_input}.{signature}"))
        self.jwks.return_value.get_signing_key_from_jwt.assert_not_called()

    def test_a_changed_claim_breaks_the_signature(self):
        header, payload, signature = token().removeprefix("Bearer ").split(".")
        body = json.loads(base64.urlsafe_b64decode(payload + "=="))
        body["sub"] = "11111111-1111-4111-8111-111111111111"
        tampered = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
        self.assertIsNone(auth.user_id(f"Bearer {header}.{tampered}.{signature}"))

    def test_an_unknown_key_id_is_refused_quietly(self):
        self.jwks.return_value.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError('Unable to find a signing key that matches: "x"')
        with self.assertNoLogs("src.auth", level="WARNING"):
            self.assertIsNone(auth.user_id(token()))

    def test_unreachable_keys_mean_signed_out_not_an_error(self):
        self.jwks.return_value.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("down")
        with self.assertLogs("src.auth", level="WARNING"):
            self.assertIsNone(auth.user_id(token()))


class ApiAuthTests(unittest.TestCase):
    def setUp(self):
        from api import main

        self.client = TestClient(main.create_app())

    def test_signed_in_questions_are_counted_by_account(self):
        from api import chat as chat_api

        with patch.object(auth, "user_id", side_effect=lambda header: USER if header == "Bearer good" else None), \
                patch.object(rate_limit, "check", return_value=rate_limit.Decision(False, 10)) as check:
            client_id = "0123456789abcdef0123456789abcdef"
            for headers in ({"Authorization": "Bearer good", "X-RagDog-Client": client_id},
                            {"Authorization": "Bearer forged", "X-RagDog-Client": client_id}):
                self.client.post("/chat", json={"question": "기침해요"}, headers=headers)
        self.assertEqual([call.args[0] for call in check.call_args_list], [f"user:{USER}", client_id])
        self.assertEqual(chat_api.person_of(None, "1.2.3.4", None), "network:1.2.3.4")

    def test_me_says_only_whether_the_token_counts(self):
        with patch.object(auth, "user_id", side_effect=lambda header: USER if header == "Bearer good" else None):
            self.assertEqual(self.client.get("/me", headers={"Authorization": "Bearer good"}).json(),
                             {"signed_in": True, "user_id": USER})
            self.assertEqual(self.client.get("/me", headers={"Authorization": "Bearer forged"}).json(),
                             {"signed_in": False, "user_id": None})
            self.assertEqual(self.client.get("/me").json(), {"signed_in": False, "user_id": None})


if __name__ == "__main__":
    unittest.main()
