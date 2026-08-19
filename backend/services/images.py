"""Decode, validate and resize uploaded imagery.

Stateless: no database, no storage, no HTTP. It takes bytes and returns bytes,
which is what makes every rule below testable without a request or a volume.

The order of operations is the security design, not an implementation detail:

1. **Size before decode.** A byte-count check costs nothing; decoding an
   attacker-chosen file does not.
2. **Identify by decoding.** The filename and the declared content type are
   strings the uploader chose. A ``.png`` that is really HTML, served back from
   our own origin, is stored XSS.
3. **Pixel count before full load.** ``Image.open`` reads the header only, so
   the dimensions are known before the bitmap is materialised — which is the
   only moment a decompression bomb can still be refused cheaply.
4. **Re-encode.** Never pass the original bytes through. Re-encoding is what
   actually strips EXIF (phone cameras write GPS coordinates into it) and what
   guarantees the stored file really is the format we think it is.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

# 12 MB. A product photo from any phone fits; a payload does not.
MAX_BYTES = 12 * 1024 * 1024

# 50 megapixels. Well past any real camera, far below what it takes to exhaust
# memory decoding a file that is only a few kilobytes on disk.
MAX_PIXELS = 50_000_000

# Deliberately not GIF (animation we do not want and cannot crop sensibly) and
# emphatically not SVG, which is XML that can carry script.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

# The three sizes the storefront needs: a listing thumbnail, a product card, and
# the PDP image. Longest edge, in pixels.
DERIVATIVE_SIZES = {"thumb": 200, "card": 600, "full": 1600}

_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


class ImageRejected(Exception):
    """The upload is not an image we are willing to store."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    format: str
    width: int
    height: int
    digest: str

    @property
    def extension(self) -> str:
        return _EXTENSIONS[self.format]


def process_upload(raw: bytes, *, filename: str = "") -> ProcessedImage:
    """Validate, re-encode and measure. ``filename`` is used for nothing but
    error messages — it is the uploader's string, not evidence."""
    if len(raw) > MAX_BYTES:
        raise ImageRejected(
            f"{filename or 'file'} is larger than {MAX_BYTES // (1024 * 1024)} MB"
        )
    if not raw:
        raise ImageRejected("the file is empty")

    try:
        probe = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError, ValueError):
        # SVG lands here too: Pillow is a raster library and cannot decode it,
        # which is exactly the answer we want.
        raise ImageRejected(
            f"{filename or 'the file'} is not a JPEG, PNG or WebP image"
        ) from None

    image_format = (probe.format or "").upper()
    if image_format not in ALLOWED_FORMATS:
        raise ImageRejected(f"{image_format or 'that format'} is not accepted")

    width, height = probe.size
    if width * height > MAX_PIXELS:
        raise ImageRejected(
            f"the image is {width}x{height}, over the {MAX_PIXELS // 1_000_000} "
            "megapixel limit"
        )

    try:
        probe.load()
    except OSError:
        raise ImageRejected("the image data is truncated or corrupt") from None

    # RGBA survives only into PNG and WebP; JPEG has no alpha channel.
    image = probe.convert("RGBA" if image_format in {"PNG", "WEBP"} else "RGB")
    clean = _encode(image, image_format)

    return ProcessedImage(
        data=clean,
        format=image_format,
        width=width,
        height=height,
        # Hashed after re-encoding, so the key identifies what we actually
        # stored rather than what was uploaded. Two identical photos with
        # different EXIF then land on one key instead of two.
        digest=hashlib.sha256(clean).hexdigest(),
    )


def derivatives(processed: ProcessedImage) -> dict[str, bytes]:
    """Thumbnail, card and full-size copies of an already-validated image.

    Never upscaled. Enlarging a small image invents detail and makes the stored
    width and height a lie, which is worse than serving a small picture.
    """
    source = Image.open(io.BytesIO(processed.data))
    source.load()

    out: dict[str, bytes] = {}
    for name, longest_edge in DERIVATIVE_SIZES.items():
        copy = source.copy()
        # thumbnail() is a no-op when the image is already smaller, which is the
        # "never upscale" rule for free.
        copy.thumbnail((longest_edge, longest_edge), Image.LANCZOS)
        out[name] = _encode(copy, processed.format)
    return out


def _encode(image: Image.Image, image_format: str) -> bytes:
    """Write the pixels out with no metadata attached.

    Pillow only carries EXIF into the output when it is passed explicitly, so
    not passing it is the strip. Saying so here because "we strip EXIF" is a
    claim that otherwise has no visible line of code behind it.
    """
    buffer = io.BytesIO()
    if image_format == "JPEG":
        image.convert("RGB").save(buffer, format="JPEG", quality=85, optimize=True)
    elif image_format == "PNG":
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.save(buffer, format="WEBP", quality=85, method=4)
    return buffer.getvalue()
