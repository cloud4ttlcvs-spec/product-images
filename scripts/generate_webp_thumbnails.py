#!/usr/bin/env python3
"""Generate deterministic WebP thumbnails beside TTL Bio image categories.

Source examples:
  product-images/products/item.png
  product-images/gifts/gift.png
  product-images/promotions/promo.jpg

Generated paths:
  product-images/thumbs/products/item.webp
  product-images/thumbs/gifts/gift.webp
  product-images/thumbs/promotions/promo.webp

The script also supports category folders at repository root. It never changes the
source images and only rewrites a thumbnail when the encoded bytes differ.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
CATEGORY_NAMES = {"products", "gifts", "promotions"}
SOURCE_SUFFIXES = {".png", ".jpg", ".jpeg"}
MAX_SIZE = (480, 480)
WEBP_QUALITY = 82
MANIFEST_PATH = REPO_ROOT / "webp-thumbnail-manifest.json"
IGNORED_PARTS = {".git", "node_modules", "thumbs", "dist", "build"}


def is_source_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
        return False
    relative_parts = path.relative_to(REPO_ROOT).parts
    if any(part in IGNORED_PARTS for part in relative_parts):
        return False
    return any(part.lower() in CATEGORY_NAMES for part in relative_parts)


def resolve_output_path(source: Path) -> Path | None:
    relative = source.relative_to(REPO_ROOT)
    parts = list(relative.parts)
    category_index = next(
        (index for index, part in enumerate(parts) if part.lower() in CATEGORY_NAMES),
        None,
    )
    if category_index is None:
        return None

    asset_root = REPO_ROOT.joinpath(*parts[:category_index])
    category = parts[category_index].lower()
    remainder = Path(*parts[category_index + 1 :]).with_suffix(".webp")
    return asset_root / "thumbs" / category / remainder


def encode_thumbnail(source: Path) -> bytes:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)

        has_alpha = image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        )
        prepared = image.convert("RGBA" if has_alpha else "RGB")

        buffer = io.BytesIO()
        prepared.save(
            buffer,
            format="WEBP",
            quality=WEBP_QUALITY,
            method=6,
            exact=has_alpha,
        )
        return buffer.getvalue()


def write_if_changed(path: Path, payload: bytes) -> bool:
    if path.exists() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return True


def main() -> int:
    sources = sorted(
        (path for path in REPO_ROOT.rglob("*") if is_source_file(path)),
        key=lambda item: item.as_posix().lower(),
    )
    if not sources:
        print("No PNG/JPEG sources found under products, gifts, or promotions.", file=sys.stderr)
        return 1

    entries: list[dict[str, int | str]] = []
    written = 0

    for source in sources:
        output = resolve_output_path(source)
        if output is None:
            continue
        try:
            encoded = encode_thumbnail(source)
        except Exception as error:  # Keep the failing file visible in Actions logs.
            print(f"Failed to process {source.relative_to(REPO_ROOT)}: {error}", file=sys.stderr)
            return 1

        if write_if_changed(output, encoded):
            written += 1

        entries.append(
            {
                "source": source.relative_to(REPO_ROOT).as_posix(),
                "thumbnail": output.relative_to(REPO_ROOT).as_posix(),
                "sourceBytes": source.stat().st_size,
                "thumbnailBytes": len(encoded),
            }
        )

    manifest = {
        "schemaVersion": 1,
        "maxWidth": MAX_SIZE[0],
        "maxHeight": MAX_SIZE[1],
        "quality": WEBP_QUALITY,
        "count": len(entries),
        "entries": entries,
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if not MANIFEST_PATH.exists() or MANIFEST_PATH.read_text(encoding="utf-8") != manifest_text:
        MANIFEST_PATH.write_text(manifest_text, encoding="utf-8")
        written += 1

    original_total = sum(int(entry["sourceBytes"]) for entry in entries)
    thumbnail_total = sum(int(entry["thumbnailBytes"]) for entry in entries)
    saving = 0.0 if original_total == 0 else (1 - thumbnail_total / original_total) * 100
    print(
        f"Generated {len(entries)} thumbnails; {written} files changed; "
        f"{original_total:,} -> {thumbnail_total:,} bytes ({saving:.1f}% smaller)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
