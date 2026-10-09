import os
from pathlib import Path

import chromadb
from mcp.server import MCPServer
from openai import OpenAI


# ============================================================
# Project configuration
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

CACHE = ROOT / ".tmp" / "cache" / "code-index"

MODEL = "text-embedding-nomic-embed-text-v1.5"

API_URL = os.getenv(
    "LM_STUDIO_URL",
    "http://127.0.0.1:1234/v1"
)

SEARCH_ROOTS = [
    ROOT / "modules",
    ROOT / "externals" / "core",
]

EXTENSIONS = {
    ".cpp",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".hxx",
    ".inl",
}

SKIP_DIRS = {
    ".git",
    ".tmp",
    ".vs",
    ".idea",
    "build",
    "node_modules",
    "__pycache__",
}


# ============================================================
# MCP SDK 2.x
# ============================================================

mcp = MCPServer("skyfire-rag")


# ============================================================
# Clients
# ============================================================

openai_client = OpenAI(
    base_url=API_URL,
    api_key="lm-studio",
    timeout=120,
)

chroma = chromadb.PersistentClient(
    path=str(CACHE / "chroma")
)


# ============================================================
# Utilities
# ============================================================

def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_source_files():
    """Iterate through C++ source files in modules and core."""

    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue

        for current, dirs, files in os.walk(root):
            dirs[:] = sorted(
                directory
                for directory in dirs
                if directory not in SKIP_DIRS
            )

            for filename in sorted(files):
                path = Path(current) / filename

                if path.suffix.lower() in EXTENSIONS:
                    yield path


# ============================================================
# Tool: Semantic search
# ============================================================

@mcp.tool()
def search_code(
    query: str,
    limit: int = 5,
) -> str:
    """
    Search SkyFire source code by semantic meaning.

    Uses Nomic embeddings from LM Studio and a local
    ChromaDB index.

    Returns relevant code fragments with source paths,
    line numbers and vector distances.
    """

    if not query.strip():
        return "Query must not be empty."

    limit = max(1, min(limit, 10))

    try:
        collection = chroma.get_collection(
            name="skyfire-code"
        )

        count = collection.count()

        if count == 0:
            return (
                "Code index is empty. "
                "Run tools/rag/index.py first."
            )

        response = openai_client.embeddings.create(
            model=MODEL,
            input=f"search_query: {query}",
        )

        vector = response.data[0].embedding

        result = collection.query(
            query_embeddings=[vector],
            n_results=min(limit, count),
            include=[
                "documents",
                "metadatas",
                "distances",
            ],
        )

        documents = result["documents"][0]
        metadata = result["metadatas"][0]
        distances = result["distances"][0]

        output = []

        for document, meta, distance in zip(
            documents,
            metadata,
            distances,
        ):
            output.append(
                f"FILE: {meta['path']}\n"
                f"LINES: {meta['start_line']}-"
                f"{meta['end_line']}\n"
                f"DISTANCE: {distance:.4f}\n"
                f"{document}"
            )

        return (
            "\n\n---\n\n".join(output)
            if output
            else "No matching code found."
        )

    except Exception as error:
        return f"Semantic search failed: {error}"


# ============================================================
# Tool: Exact symbol search
# ============================================================

@mcp.tool()
def find_symbol(
    symbol: str,
    limit: int = 10,
) -> str:
    """
    Find exact C++ symbol text in modules and core.

    Useful for locating functions, method calls,
    classes, enum values and API declarations.

    This is a textual search, not a C++ AST resolver.
    """

    if not symbol.strip():
        return "Symbol must not be empty."

    limit = max(1, min(limit, 30))

    matches = []

    for path in iter_source_files():
        try:
            with path.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as source:

                for number, line in enumerate(source, 1):
                    if symbol in line:
                        matches.append(
                            f"{relative(path)}:"
                            f"{number}: "
                            f"{line.strip()[:300]}"
                        )

                        if len(matches) >= limit:
                            return "\n".join(matches)

        except OSError:
            continue

    return (
        "\n".join(matches)
        if matches
        else f"Symbol not found: {symbol}"
    )


# ============================================================
# Tool: Header discovery
# ============================================================

@mcp.tool()
def find_header(
    name: str,
    limit: int = 20,
) -> str:
    """
    Recursively locate C++ header files by filename.

    Searches the local modules and SkyFire core,
    returning paths relative to the repository root.
    """

    if not name.strip():
        return "Header name must not be empty."

    if "/" in name or "\\" in name:
        return "Provide a filename, not a path."

    limit = max(1, min(limit, 50))

    matches = []

    for path in iter_source_files():
        if path.name.lower() == name.lower():
            matches.append(relative(path))

            if len(matches) >= limit:
                break

    return (
        "\n".join(matches)
        if matches
        else f"Header not found: {name}"
    )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
