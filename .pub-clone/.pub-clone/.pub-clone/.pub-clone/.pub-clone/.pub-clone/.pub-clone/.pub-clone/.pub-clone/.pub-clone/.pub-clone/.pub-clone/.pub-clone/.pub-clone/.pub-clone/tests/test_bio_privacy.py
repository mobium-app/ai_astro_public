"""Testy ochrony biometrii (Faza 6): szyfrowanie embeddingów + retencja zobaczeń."""

import os
import tempfile
import unittest
from unittest import mock

from astro import config
from astro.memory import biocrypto
from astro.memory import store as memory


class TestBioCrypto(unittest.TestCase):
    def setUp(self):
        self.key = os.path.join(tempfile.mkdtemp(), "bio.key")

    def test_roundtrip_with_key(self):
        with mock.patch.object(config, "BIO_KEY_FILE", self.key), \
             mock.patch.object(config, "BIO_ENCRYPT", True):
            blob = biocrypto.encrypt(b"\x01\x02\x03\x04")
        self.assertTrue(biocrypto.is_encrypted(blob))
        with mock.patch.object(config, "BIO_KEY_FILE", self.key), \
             mock.patch.object(config, "BIO_ENCRYPT", True):
            self.assertEqual(biocrypto.decrypt(blob), b"\x01\x02\x03\x04")

    def test_missing_key_returns_ciphertext_empty(self):
        blob = biocrypto.encrypt(b"\x01\x02\x03")  # z kluczem
        with mock.patch.object(config, "BIO_KEY_FILE", "/nie/ma/klucza"):
            self.assertEqual(biocrypto.decrypt(blob), b"")

    def test_plaintext_passthrough(self):
        with mock.patch.object(config, "BIO_KEY_FILE", "/nie/ma"):
            self.assertEqual(biocrypto.decrypt(b"plain"), b"plain")


class TestEncryptedStore(unittest.TestCase):
    def test_faces_encrypted_at_rest(self):
        key = os.path.join(tempfile.mkdtemp(), "bio.key")
        with mock.patch.object(config, "BIO_KEY_FILE", key), \
             mock.patch.object(config, "BIO_ENCRYPT", True):
            mem = memory.Memory(":memory:")
            mem.add_face("Anna", [1.0, 2.0, 3.0])
            raw = mem.con.execute("SELECT embedding FROM faces").fetchone()[0]
            self.assertTrue(biocrypto.is_encrypted(raw))
            name, score = mem.match_face([1.0, 2.0, 3.0], threshold=0.5)
            self.assertEqual(name, "Anna")
            self.assertAlmostEqual(score, 1.0, places=3)

    def test_bodies_encrypted_and_match(self):
        key = os.path.join(tempfile.mkdtemp(), "bio.key")
        with mock.patch.object(config, "BIO_KEY_FILE", key), \
             mock.patch.object(config, "BIO_ENCRYPT", True):
            mem = memory.Memory(":memory:")
            mem.add_body("Konrad", [0.0, 1.0, 0.0])
            raw = mem.con.execute("SELECT embedding FROM bodies").fetchone()[0]
            self.assertTrue(biocrypto.is_encrypted(raw))
            name, _ = mem.match_body([0.0, 1.0, 0.0], threshold=0.5)
            self.assertEqual(name, "Konrad")

    def test_migration_encrypts_plaintext(self):
        key = os.path.join(tempfile.mkdtemp(), "bio.key")
        with mock.patch.object(config, "BIO_KEY_FILE", key), \
             mock.patch.object(config, "BIO_ENCRYPT", True):
            mem = memory.Memory(":memory:")
            import array
            plain = array.array("f", [1.0, 0.0]).tobytes()
            mem.con.execute("INSERT INTO faces(ts,name,embedding,count,last) "
                            "VALUES(0,'Old',?,1,0)", (plain,))
            mem.con.commit()
            changed = mem.encrypt_bio()
            self.assertEqual(changed, 1)
            raw = mem.con.execute("SELECT embedding FROM faces").fetchone()[0]
            self.assertTrue(biocrypto.is_encrypted(raw))
            self.assertEqual(mem.list_faces()[0]["name"], "Old")


class TestRetention(unittest.TestCase):
    def test_purge_sightings(self):
        with mock.patch.object(config, "BIO_KEY_FILE", os.path.join(tempfile.mkdtemp(),
                                                                    "k")):
            mem = memory.Memory(":memory:")
            old = 1.0  # 1970
            mem.con.execute("INSERT INTO face_sightings(ts,name,score,known) "
                            "VALUES(?, 'Old', 0.5, 1)", (old,))
            mem.con.execute("INSERT INTO face_sightings(ts,name,score,known) "
                            "VALUES(?, 'New', 0.5, 1)", (__import__("time").time(),))
            mem.con.commit()
            n = mem.purge_sightings(days=90)
            self.assertEqual(n, 1)
            names = [r["name"] for r in mem.recent_sightings(10)]
            self.assertIn("New", names)
            self.assertNotIn("Old", names)


if __name__ == "__main__":
    unittest.main()
