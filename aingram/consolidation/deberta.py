# aingram/consolidation/deberta.py
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from aingram.exceptions import ModelNotFoundError
from aingram.types import ContradictionVerdict

_HF_REPO = 'aingram/deberta-v3-base-nli-onnx'
_DEFAULT_BATCH_SIZE = 16


def _softmax(logits: np.ndarray) -> np.ndarray:
    exp = np.exp(logits - np.max(logits))
    return exp / exp.sum()


def _softmax_batch(logits: np.ndarray) -> np.ndarray:
    # logits: (N, C) — stable row-wise softmax
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


class DeBERTaContradictionClassifier:
    """Contradiction classifier using DeBERTa-v3-base NLI via ONNX."""

    def __init__(
        self,
        *,
        threshold: float = 0.7,
        onnx_provider: str | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._threshold = threshold
        self._onnx_provider = onnx_provider
        self._batch_size = max(1, batch_size)
        self._session = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        try:
            from huggingface_hub import hf_hub_download

            model_path = hf_hub_download(_HF_REPO, 'model.onnx')
            tokenizer_path = hf_hub_download(_HF_REPO, 'tokenizer.json')
            from tokenizers import Tokenizer

            self._tokenizer = Tokenizer.from_file(tokenizer_path)
            import onnxruntime as ort

            from aingram.processing.embedder import _select_providers

            providers = _select_providers(
                set(ort.get_available_providers()),
                self._onnx_provider,
            )
            self._session = ort.InferenceSession(model_path, providers=providers)
        except Exception as exc:
            raise ModelNotFoundError(
                f'Failed to load DeBERTa NLI model from {_HF_REPO}: {exc}'
            ) from exc

    def classify(self, text_a: str, text_b: str) -> ContradictionVerdict:
        self._ensure_loaded()
        encoding = self._tokenizer.encode(text_a, text_b)
        available = {
            'input_ids': np.array([encoding.ids], dtype=np.int64),
            'attention_mask': np.array([encoding.attention_mask], dtype=np.int64),
            'token_type_ids': np.array([encoding.type_ids], dtype=np.int64),
        }
        expected = {inp.name for inp in self._session.get_inputs()}
        feed = {k: v for k, v in available.items() if k in expected}
        logits = self._session.run(None, feed)[0][0]
        probs = _softmax(logits)
        contradiction_prob = float(probs[2])
        return ContradictionVerdict(
            contradicts=contradiction_prob > self._threshold,
            confidence=contradiction_prob,
            superseded_index=None,
        )

    def classify_batch(
        self, pairs: Sequence[tuple[str, str]]
    ) -> list[ContradictionVerdict]:
        """Batch-classify sentence pairs. Processes in chunks of self._batch_size."""
        if not pairs:
            return []
        self._ensure_loaded()
        expected = {inp.name for inp in self._session.get_inputs()}

        verdicts: list[ContradictionVerdict] = []
        for start in range(0, len(pairs), self._batch_size):
            chunk = list(pairs[start : start + self._batch_size])
            verdicts.extend(self._run_chunk(chunk, expected))
        return verdicts

    def _run_chunk(
        self, chunk: list[tuple[str, str]], expected: set[str]
    ) -> list[ContradictionVerdict]:
        encodings = self._tokenizer.encode_batch(chunk)
        max_len = max(len(e.ids) for e in encodings)
        n = len(encodings)

        input_ids = np.zeros((n, max_len), dtype=np.int64)
        attention_mask = np.zeros((n, max_len), dtype=np.int64)
        token_type_ids = np.zeros((n, max_len), dtype=np.int64)
        for i, e in enumerate(encodings):
            k = len(e.ids)
            input_ids[i, :k] = e.ids
            attention_mask[i, :k] = e.attention_mask
            token_type_ids[i, :k] = e.type_ids

        available = {
            'input_ids': input_ids,
            'attention_mask': attention_mask,
            'token_type_ids': token_type_ids,
        }
        feed = {k: v for k, v in available.items() if k in expected}
        logits_batch = np.asarray(self._session.run(None, feed)[0])
        probs = _softmax_batch(logits_batch)

        return [
            ContradictionVerdict(
                contradicts=float(row[2]) > self._threshold,
                confidence=float(row[2]),
                superseded_index=None,
            )
            for row in probs
        ]
