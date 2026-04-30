"""
Robust HuggingFace model loading helpers used by every transformers-based
package (CLIP, Depth Anything, Grounding DINO, ...).

The high-level ``transformers.from_pretrained`` issues HEAD requests to
verify each shard against the hub. On flaky networks (Windows ``WinError
10054``, mid-handshake SSL resets, ISP-level disconnects) those HEAD
calls can fail even when the bytes are already on disk, leaving the
caller with a confusing "missing preprocessor_config.json" error.

The pattern in this module sidesteps that:

1. Atomically materialise the model snapshot via
   :func:`huggingface_hub.snapshot_download` — writes to ``.incomplete``
   files and renames on success, retries on connection drops, and
   tolerates partial caches.
2. Point ``from_pretrained`` at the resulting **local snapshot path**
   with ``local_files_only=True`` so the load makes zero network calls.
3. If a particular processor / model class can't read the local
   snapshot, walk a small fallback chain before giving up.

This is the pattern used by all of stride's HF-based nodes; centralising
it here keeps a single source of truth for the retry, error message,
and cache-hint behaviour.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Optional, Sequence

from .errors import NodeMissingDependencyError


_DEFAULT_ALLOW_PATTERNS: Sequence[str] = (
    "*.json", "*.txt", "*.model",
    "*.safetensors", "*.bin",
    "tokenizer*", "vocab*", "merges*",
)


def ensure_snapshot(
    checkpoint: str,
    *,
    allow_patterns: Optional[Sequence[str]] = None,
    max_workers: int = 4,
) -> str:
    """Atomically materialise a HF model snapshot in the local hub cache.

    Returns the local snapshot path. Raises :class:`NodeMissingDependencyError`
    with an actionable message on failure (network instability, missing
    repo, etc.).
    """
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:  # pragma: no cover - transformers ships hf_hub
        raise NodeMissingDependencyError(
            "huggingface_hub not installed (pip install huggingface_hub)"
        ) from exc

    try:
        return snapshot_download(
            repo_id=checkpoint,
            allow_patterns=list(allow_patterns or _DEFAULT_ALLOW_PATTERNS),
            max_workers=max_workers,
        )
    except Exception as exc:  # noqa: BLE001 — wrap into a clean NodeError
        safe_dir = checkpoint.replace("/", "--")
        raise NodeMissingDependencyError(
            f"Failed to download '{checkpoint}' from HuggingFace. "
            f"This usually means the network connection to huggingface.co is "
            f"unstable (WinError 10054, SSL reset, ISP block, rate-limit). "
            f"Try again on a stable connection. If the error mentions a partial "
            f"cache, delete '~/.cache/huggingface/hub/models--{safe_dir}' first. "
            f"Underlying error: {exc}"
        ) from exc


def load_from_snapshot(
    snapshot_path: str,
    classes: Iterable[Optional[type]],
    *,
    kind: str = "model",
    extra_kwargs: Optional[dict] = None,
) -> Any:
    """Walk a list of HF classes calling ``from_pretrained`` on each.

    Returns the first one that loads. Skips ``None`` entries (so callers
    can put optional classes in the list without guarding). Raises
    :class:`NodeMissingDependencyError` if every class fails — wrapping
    the *last* underlying error.
    """
    last_err: Exception | None = None
    extra = extra_kwargs or {}
    for klass in classes:
        if klass is None:
            continue
        try:
            return klass.from_pretrained(snapshot_path, local_files_only=True, **extra)
        except Exception as exc:  # noqa: BLE001 — re-raised below if all fail
            last_err = exc
            continue
    raise NodeMissingDependencyError(
        f"Snapshot at '{snapshot_path}' downloaded but no compatible "
        f"{kind} class could load it. Underlying error: {last_err}"
    ) from last_err


def load_pretrained(
    checkpoint: str,
    classes: Iterable[Optional[type]],
    *,
    kind: str = "model",
    allow_patterns: Optional[Sequence[str]] = None,
    extra_kwargs: Optional[dict] = None,
) -> Any:
    """One-shot helper: download the snapshot and load via the class chain.

    Equivalent to ``load_from_snapshot(ensure_snapshot(...), classes)``
    but passing through ``allow_patterns`` and ``extra_kwargs`` to the
    relevant phase.
    """
    snapshot_path = ensure_snapshot(checkpoint, allow_patterns=allow_patterns)
    return load_from_snapshot(snapshot_path, classes, kind=kind, extra_kwargs=extra_kwargs)


__all__ = [
    "ensure_snapshot",
    "load_from_snapshot",
    "load_pretrained",
]
