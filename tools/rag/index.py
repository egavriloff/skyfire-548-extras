import argparse
import hashlib
import json
import os
from pathlib import Path

import chromadb
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".tmp" / "cache" / "code-index"
MANIFEST = CACHE / "manifest.json"

MODEL = "text-embedding-nomic-embed-text-v1.5"
API_URL = os.getenv(
    "LM_STUDIO_URL",
    "http://127.0.0.1:1234/v1"
)

EXTENSIONS = {
    ".cpp", ".cc", ".c", ".h", ".hpp", ".hxx",
    ".inl", ".cmake", ".yml", ".yaml",
    ".sql", ".conf"
}

SKIP_DIRS = {
    ".git", ".vs", ".idea", ".tmp",
    "build", "node_modules", "__pycache__"
}

CHUNK_LINES = 40
OVERLAP_LINES = 10
BATCH_SIZE = 16
MAX_FILE_BYTES = 2_000_000

client = OpenAI(
    base_url=API_URL,
    api_key="lm-studio",
    timeout=120
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text("utf-8"))
    return {}


def save_manifest(manifest):
    CACHE.mkdir(parents=True, exist_ok=True)
    temp = MANIFEST.with_suffix(".tmp")
    temp.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8"
    )
    temp.replace(MANIFEST)


def discover_files(roots):
    for root_name in roots:
        folder = ROOT / root_name

        if not folder.is_dir():
            print(f"Skipping missing: {folder}")
            continue

        for current, dirs, files in os.walk(folder):
            dirs[:] = sorted(
                d for d in dirs
                if d not in SKIP_DIRS
            )

            for filename in sorted(files):
                path = Path(current) / filename

                if (
                    path.suffix.lower() in EXTENSIONS
                    or filename == "CMakeLists.txt"
                ):
                    if path.stat().st_size <= MAX_FILE_BYTES:
                        yield path


def chunks_for(path, content):
    lines = content.splitlines()
    step = CHUNK_LINES - OVERLAP_LINES

    for start in range(0, len(lines), step):
        end = min(start + CHUNK_LINES, len(lines))
        fragment = "\n".join(lines[start:end])

        if not fragment.strip():
            continue

        relative = path.relative_to(ROOT).as_posix()

        document = (
            f"search_document: File: {relative}\n"
            f"Lines: {start + 1}-{end}\n"
            f"{fragment}"
        )

        yield {
            "id": sha256(
                f"{relative}:{start}".encode()
            ),
            "document": document,
            "metadata": {
                "path": relative,
                "start_line": start + 1,
                "end_line": end
            }
        }


def embed_batch(documents):
    response = client.embeddings.create(
        model=MODEL,
        input=documents
    )

    return [
        item.embedding
        for item in sorted(
            response.data,
            key=lambda x: x.index
        )
    ]


def index_file(collection, path):
    raw = path.read_bytes()
    content = raw.decode("utf-8", errors="replace")
    chunks = list(chunks_for(path, content))

    records = []

    for offset in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[offset:offset + BATCH_SIZE]
        vectors = embed_batch(
            [item["document"] for item in batch]
        )

        for item, vector in zip(batch, vectors):
            records.append((item, vector))

    relative = path.relative_to(ROOT).as_posix()

    # All embeddings are ready before replacing old data.
    old = collection.get(where={"path": relative})

    if old["ids"]:
        collection.delete(ids=old["ids"])

    for offset in range(0, len(records), BATCH_SIZE):
        batch = records[offset:offset + BATCH_SIZE]

        collection.upsert(
            ids=[r[0]["id"] for r in batch],
            documents=[r[0]["document"] for r in batch],
            embeddings=[r[1] for r in batch],
            metadatas=[r[0]["metadata"] for r in batch]
        )

    return len(chunks)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--roots",
        nargs="+",
        default=["modules", "externals/core"]
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=0
    )

    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)

    chroma = chromadb.PersistentClient(
        path=str(CACHE / "chroma")
    )

    collection = chroma.get_or_create_collection(
        name="skyfire-code",
        metadata={"hnsw:space": "cosine"}
    )

    manifest = load_manifest()
    changed = 0
    skipped = 0

    for path in discover_files(args.roots):
        relative = path.relative_to(ROOT).as_posix()
        digest = sha256(path.read_bytes())

        if manifest.get(relative) == digest:
            skipped += 1
            continue

        try:
            count = index_file(collection, path)
            manifest[relative] = digest
            save_manifest(manifest)

            changed += 1
            print(f"Indexed: {relative} ({count} chunks)")

        except Exception as error:
            print(f"ERROR: {relative}: {error}")

        if args.limit_files and changed >= args.limit_files:
            break

    print(
        f"Done. Indexed: {changed}, "
        f"unchanged: {skipped}"
    )


if __name__ == "__main__":
    main()
