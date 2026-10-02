"""Debug: embed every chunk and write the vectors to data/debug/embeddings.txt.

Run from the project root:  python scripts/dump_embeddings.py
One block per chunk: chunk_id, url, section_title, a text preview, and all 384
dimensions. Also prints a sanity check (norms, nearest chunks for a probe query).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.chunk import chunk_documents  # noqa: E402
from src.ingest.embed import EMBED_DIM, MODEL_ID, embed_texts  # noqa: E402
from src.ingest.load import load_documents  # noqa: E402

OUT = PROJECT_ROOT / "data" / "debug" / "embeddings.txt"
PROBE = "What is the exit load of HDFC Small Cap Fund?"


def main() -> None:
    chunks = chunk_documents(load_documents())
    vectors = embed_texts([c.text for c in chunks])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        f.write(f"model={MODEL_ID}  dim={EMBED_DIM}  chunks={len(chunks)}\n")
        f.write("Vectors are L2-normalized, so dot product = cosine similarity.\n")
        for i, (c, v) in enumerate(zip(chunks, vectors), 1):
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"CHUNK {i}/{len(chunks)}  chunk_id={c.chunk_id}\n")
            f.write(f"url: {c.url}\n")
            f.write(f"section_title: {c.section_title}\n")
            f.write(f"text: {c.text[:150].replace(chr(10), ' ')}...\n")
            f.write(f"norm: {np.linalg.norm(v):.4f}\n")
            f.write("vector:\n")
            for row in range(0, EMBED_DIM, 8):
                f.write("  " + " ".join(f"{x:+.5f}" for x in v[row : row + 8]) + "\n")

    norms = np.linalg.norm(vectors, axis=1)
    print(f"wrote {len(chunks)} embeddings to {OUT}")
    print(f"shape={vectors.shape}  norm min/max={norms.min():.4f}/{norms.max():.4f}")
    scores = vectors @ embed_texts([PROBE])[0]
    print(f"\nprobe: {PROBE}")
    for idx in np.argsort(-scores)[:3]:
        c = chunks[idx]
        print(f"  {scores[idx]:.3f}  [{c.section_title[:40]}]  {c.url[-60:]}")


if __name__ == "__main__":
    main()
