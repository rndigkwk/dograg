import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.memory_limits import block_torch_imports
from src.onnx_embeddings import OnnxSentenceEmbeddings, l2_normalize, mean_pool


class FakeTokenizer:
    """Token ids are character codes; pads to the longest text with id 1 like the real tokenizer."""

    def encode_batch(self, texts):
        longest = max(len(t) for t in texts)
        return [
            SimpleNamespace(
                ids=[ord(c) for c in t] + [1] * (longest - len(t)),
                attention_mask=[1] * len(t) + [0] * (longest - len(t)),
            )
            for t in texts
        ]


class FakeSession:
    """last_hidden_state: every token's vector is [id, 1, 0]."""

    def __init__(self):
        self.calls = []

    def get_inputs(self):
        return [SimpleNamespace(name="input_ids"), SimpleNamespace(name="attention_mask")]

    def run(self, _outputs, feeds):
        self.calls.append(feeds)
        ids = feeds["input_ids"].astype(np.float32)
        return [np.stack([ids, np.ones_like(ids), np.zeros_like(ids)], axis=-1)]


class OnnxEmbeddingTests(unittest.TestCase):
    def test_mean_pool_ignores_padding(self):
        hidden = np.array([[[2.0, 0.0], [4.0, 0.0], [100.0, 100.0]]])
        mask = np.array([[1, 1, 0]])
        np.testing.assert_allclose(mean_pool(hidden, mask), [[3.0, 0.0]])

    def test_vectors_are_unit_length(self):
        vectors = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
        np.testing.assert_allclose(vectors[0], [0.6, 0.8])
        np.testing.assert_allclose(vectors[1], [0.0, 0.0])  # no division by zero

    def test_padding_does_not_change_a_text_embedding(self):
        model = OnnxSentenceEmbeddings(FakeSession(), FakeTokenizer())
        alone = model.embed_query("ab")
        batched = model.embed_documents(["ab", "abcdef"])[0]
        np.testing.assert_allclose(alone, batched, rtol=1e-6)
        self.assertAlmostEqual(float(np.linalg.norm(alone)), 1.0, places=6)

    def test_documents_are_embedded_in_batches(self):
        session = FakeSession()
        model = OnnxSentenceEmbeddings(session, FakeTokenizer())
        vectors = model.embed_documents([f"t{i}" for i in range(70)])
        self.assertEqual(len(vectors), 70)
        self.assertEqual([len(call["input_ids"]) for call in session.calls], [32, 32, 6])
        self.assertNotIn("token_type_ids", session.calls[0])

    def test_block_torch_imports_makes_transformers_unimportable(self):
        with patch.dict(sys.modules):
            sys.modules.pop("transformers", None)
            block_torch_imports()
            with self.assertRaises(ImportError):
                import transformers  # noqa: F401


if __name__ == "__main__":
    unittest.main()
