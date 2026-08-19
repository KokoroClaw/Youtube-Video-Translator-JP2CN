import tempfile
import unittest
from pathlib import Path

from src.glossary import GlossaryProtector, GlossaryStore


class GlossaryStoreTests(unittest.TestCase):
    def test_crud_persists_terms(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GlossaryStore(Path(directory) / "glossary.json")
            term = store.add_term("先輩", "前辈", "称呼")
            self.assertEqual(store.enabled_terms()[0]["target"], "前辈")

            updated = store.update_term(term["id"], {"target": "学长", "enabled": False})
            self.assertEqual(updated["target"], "学长")
            self.assertEqual(store.enabled_terms(), [])

            store.delete_term(term["id"])
            self.assertEqual(store.list_terms(), [])

    def test_duplicate_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GlossaryStore(Path(directory) / "glossary.json")
            store.add_term("先生", "老师")
            with self.assertRaisesRegex(ValueError, "已存在"):
                store.add_term("先生", "先生")


class GlossaryProtectorTests(unittest.TestCase):
    def test_longest_term_wins_and_target_is_restored(self):
        protector = GlossaryProtector([
            {"source": "東京", "target": "东京", "enabled": True},
            {"source": "東京大学", "target": "东京大学", "enabled": True},
        ])
        protected, markers = protector.protect("東京大学と東京")

        self.assertEqual(len(markers), 2)
        self.assertNotIn("東京", protected)
        self.assertEqual(protector.restore(protected, markers), "东京大学と东京")

    def test_missing_marker_is_rejected(self):
        protector = GlossaryProtector([
            {"source": "先輩", "target": "前辈", "enabled": True},
        ])
        _protected, markers = protector.protect("先輩")
        with self.assertRaisesRegex(RuntimeError, "丢失"):
            protector.restore("学长", markers)


if __name__ == "__main__":
    unittest.main()
