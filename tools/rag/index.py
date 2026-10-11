import argparse
import hashlib
import json
import os
from pathlib import Path

import chromadb
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".tmp" / "cache" / "code-index"

PROVIDER = os.getenv("RAG_PROVIDER", "ollama").lower()

if PROVIDER == "ollama":
    MODEL = os.getenv("RAG_EMBEDDING_MODEL", "qwen-embed-2k")
    API_URL = os.getenv(
        "RAG_EMBEDDING_URL",
        "http://127.0.0.1:11434/v1",
    )
    API_KEY = "ollama"
    COLLECTION_NAME = "skyfire-qwen3-06b"
    MANIFEST = CACHE / "manifest-qwen3-06b.json"

elif PROVIDER == "lmstudio":
    MODEL = os.getenv(
        "RAG_EMBEDDING_MODEL",
        "text-embedding-nomic-embed-text-v1.5",
    )
    API_URL = os.getenv(
        "RAG_EMBEDDING_URL",
        "http://127.0.0.1:1234/v1",
    )
    API_KEY = "lm-studio"
    COLLECTION_NAME = "skyfire-code"
    MANIFEST = CACHE / "manifest.json"

else:
    raise ValueError(f"Unsupported RAG provider: {PROVIDER}")


EXTENSIONS = {
    ".cpp", ".cc", ".c", ".h", ".hpp", ".hxx",
    ".inl", ".cmake", ".yml", ".yaml",
    ".sql", ".conf",
}

SKIP_DIRS = {
    ".git", ".vs", ".idea", ".tmp",
    "build", "node_modules", "__pycache__",
}

CHUNK_LINES = 40
OVERLAP_LINES = 10
BATCH_SIZE = 16
MAX_FILE_BYTES = 2_000_000

DOCUMENT_FORMAT = (
    "qwen3-plain-v1"
    if PROVIDER == "ollama"
    else "nomic-search-document-v1"
)

client = OpenAI(
    base_url=API_URL,
    api_key=API_KEY,
    timeout=120,
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def load_manifest():
    if MANIFEST.exists():
        data = json.loads(MANIFEST.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid manifest")
        return data
    return {}


def save_manifest(manifest):
    CACHE.mkdir(parents=True, exist_ok=True)
    temp = MANIFEST.with_suffix(".tmp")
    temp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp.replace(MANIFEST)


def get_collection(chroma):
    metadata = {
        "rag_provider": PROVIDER,
        "embedding_model": MODEL,
        "document_format": DOCUMENT_FORMAT,
    }

    try:
        collection = chroma.get_collection(name=COLLECTION_NAME)
    except chromadb.errors.NotFoundError:
        return chroma.create_collection(
            name=COLLECTION_NAME,
            metadata={
                **metadata,
                "hnsw:space": "cosine",
            },
        )

    existing = collection.metadata or {}

    for key, value in metadata.items():
        actual = existing.get(key)

        if actual is not None and actual != value:
            raise RuntimeError(
                f"Collection {COLLECTION_NAME}: "
                f"{key}={actual!r}, expected {value!r}"
            )

    if PROVIDER == "ollama":
        if any(existing.get(k) != v for k, v in metadata.items()):
            if collection.count() > 0:
                raise RuntimeError(
                    "Existing Qwen collection has no matching "
                    "embedding metadata. Refusing to mix vectors."
                )
            collection.modify(metadata={
                **existing,
                **metadata,
            })

    return collection


def discover_files(roots):
    seen = set()

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

                if not (
                    path.suffix.lower() in EXTENSIONS
                    or filename == "CMakeLists.txt"
                ):
                    continue

                if path.stat().st_size > MAX_FILE_BYTES:
                    continue

                key = relative(path)
                if key in seen:
                    continue

                seen.add(key)
                yield path


def chunks_for(path, content):
    lines = content.splitlines()
    step = CHUNK_LINES - OVERLAP_LINES
    source_path = relative(path)

    for start in range(0, len(lines), step):
        end = min(start + CHUNK_LINES, len(lines))
        fragment = "\n".join(lines[start:end])

        if not fragment.strip():
            continue

        plain_document = (
            f"File: {source_path}\n"
            f"Lines: {start + 1}-{end}\n"
            f"{fragment}"
        )

        document = (
            f"search_document: {plain_document}"
            if PROVIDER == "lmstudio"
            else plain_document
        )

        yield {
            "id": sha256(f"{source_path}:{start}".encode()),
            "document": document,
            "metadata": {
                "path": source_path,
                "start_line": start + 1,
                "end_line": end,
            },
        }


def embed_batch(documents):
    if not documents:
        return []

    response = client.embeddings.create(
        model=MODEL,
        input=documents,
    )

    results = sorted(response.data, key=lambda item: item.index)

    if len(results) != len(documents):
        raise RuntimeError(
            f"Embedding count mismatch: "
            f"{len(documents)} sent, {len(results)} received"
        )

    return [item.embedding for item in results]


def index_file(collection, path):
    raw = path.read_bytes()
    content = raw.decode("utf-8", errors="replace")
    chunks = list(chunks_for(path, content))
    records = []

    # Generate vectors before replacing old records.
    for offset in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[offset:offset + BATCH_SIZE]
        vectors = embed_batch(
            [item["document"] for item in batch]
        )
        records.extend(zip(batch, vectors))

    source_path = relative(path)
    old = collection.get(where={"path": source_path})

    if old["ids"]:
        collection.delete(ids=old["ids"])

    for offset in range(0, len(records), BATCH_SIZE):
        batch = records[offset:offset + BATCH_SIZE]

        collection.upsert(
            ids=[r[0]["id"] for r in batch],
            documents=[r[0]["document"] for r in batch],
            embeddings=[r[1] for r in batch],
            metadatas=[r[0]["metadata"] for r in batch],
        )

    return len(chunks)


def remove_deleted_files(collection, manifest, discovered):
    removed = 0

    for source_path in list(manifest):
        if source_path in discovered:
            continue

        records = collection.get(where={"path": source_path})

        if records["ids"]:
            collection.delete(ids=records["ids"])

        del manifest[source_path]
        removed += 1
        print(f"Removed: {source_path}")

    return removed


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--roots",
        nargs="+",
        default=["modules", "externals/core"],
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=0,
    )

    args = parser.parse_args()

    if args.limit_files < 0:
        parser.error("--limit-files must be >= 0")

    CACHE.mkdir(parents=True, exist_ok=True)

    chroma = chromadb.PersistentClient(
        path=str(CACHE / "chroma")
    )

    collection = get_collection(chroma)
    manifest = load_manifest()

    print(f"Provider:   {PROVIDER}")
    print(f"Model:      {MODEL}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Manifest:   {MANIFEST.name}")
    print(f"API:        {API_URL}")

    changed = 0
    skipped = 0
    errors = 0

    paths = list(discover_files(args.roots))
    discovered = {relative(path) for path in paths}

    full_scan = (
        args.limit_files == 0
        and args.roots == ["modules", "externals/core"]
        and all((ROOT / name).is_dir() for name in args.roots)
    )

    for path in paths:
        source_path = relative(path)
        digest = sha256(path.read_bytes())

        if manifest.get(source_path) == digest:
            skipped += 1
            continue

        try:
            count = index_file(collection, path)
            manifest[source_path] = digest
            save_manifest(manifest)

            changed += 1
            print(f"Indexed: {source_path} ({count} chunks)")

        except Exception as error:
            errors += 1
            print(f"ERROR: {source_path}: {error}")

        if args.limit_files and changed >= args.limit_files:
            break

    removed = 0

    if full_scan and errors == 0:
        removed = remove_deleted_files(
            collection,
            manifest,
            discovered,
        )
        save_manifest(manifest)

    print(
        f"Done. Indexed: {changed}, "
        f"unchanged: {skipped}, "
        f"removed: {removed}, errors: {errors}"
    )
    print(f"Collection records: {collection.count()}")


if __name__ == "__main__":
    main()
