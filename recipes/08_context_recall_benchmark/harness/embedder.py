"""Deterministic hashing embedder. Every store gets THESE EXACT vectors.

Bag of word 1/2-grams -> signed feature hashing (BLAKE2) -> L2 normalize.
Pure function of the text: same corpus, same bytes, every machine.
No model downloads; the benchmark is about retrieval structure, not encoders.
"""
import hashlib
import re
import struct

import numpy as np

DIM = 256


def embed(text: str) -> np.ndarray:
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    grams = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    vec = np.zeros(DIM, dtype=np.float32)
    for gram in grams:
        digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
        idx = struct.unpack("<I", digest[:4])[0] % DIM
        vec[idx] += 1.0 if digest[4] & 1 else -1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec
