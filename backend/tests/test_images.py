"""Image decoding, validation and derivative generation.

Every rule here exists because the alternative is a security hole or a broken
page, and the reasons are not interchangeable:

* identify by **decoding**, never by extension or declared content type — those
  are attacker-supplied strings
* reject SVG — it is XML that can carry script, and a product photo never needs
  it
* strip EXIF — phone cameras write GPS coordinates into it
* measure the dimensions ourselves — ``width``/``height`` are NOT NULL because
  section 8A needs them to hold CLS under 0.1, and an operator typing them is an
  operator guessing
"""

import io

import pytest
from PIL import Image

from services.images import (
    ImageRejected,
    MAX_BYTES,
    MAX_PIXELS,
    derivatives,
    process_upload,
)


def _png(width=800, height=600, colour=(200, 30, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_with_gps() -> bytes:
    """A JPEG carrying EXIF, including a GPS tag."""
    buffer = io.BytesIO()
    image = Image.new("RGB", (400, 300), (10, 90, 200))
    exif = image.getexif()
    exif[0x010F] = "TestCamera"          # Make
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}  # GPSInfo
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_a_png_is_accepted_and_measured():
    result = process_upload(_png(800, 600), filename="photo.png")

    assert result.width == 800
    assert result.height == 600
    assert result.format == "PNG"


def test_dimensions_come_from_the_pixels_not_from_the_caller():
    """The columns are NOT NULL and feed the CLS-safe <img> attributes."""
    result = process_upload(_png(123, 45), filename="whatever.jpg")

    assert (result.width, result.height) == (123, 45)


def test_a_file_lying_about_its_extension_is_identified_by_content():
    """A PNG named .jpg is still a PNG. Trusting the name is how a .jpg that is
    really an HTML file ends up served from our own origin."""
    result = process_upload(_png(), filename="not-really.jpg")

    assert result.format == "PNG"


def test_svg_is_rejected():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

    with pytest.raises(ImageRejected):
        process_upload(svg, filename="logo.svg")


def test_a_text_file_renamed_to_png_is_rejected():
    with pytest.raises(ImageRejected):
        process_upload(b"not an image at all", filename="payload.png")


def test_an_html_file_is_rejected():
    """Stored under our origin and served back, this would be stored XSS."""
    with pytest.raises(ImageRejected):
        process_upload(b"<!doctype html><script>alert(1)</script>", filename="x.png")


def test_a_gif_is_rejected_as_outside_the_allow_list():
    buffer = io.BytesIO()
    Image.new("P", (10, 10)).save(buffer, format="GIF")

    with pytest.raises(ImageRejected):
        process_upload(buffer.getvalue(), filename="animation.gif")


def test_an_oversized_file_is_rejected_before_decoding():
    with pytest.raises(ImageRejected):
        process_upload(b"\x89PNG\r\n\x1a\n" + b"0" * MAX_BYTES, filename="huge.png")


def test_a_decompression_bomb_is_rejected():
    """A small file that decodes to an enormous bitmap. The guard is on the
    pixel count, because the byte count says nothing about it."""
    side = int(MAX_PIXELS**0.5) + 1000
    buffer = io.BytesIO()
    Image.new("L", (side, side)).save(buffer, format="PNG")

    with pytest.raises(ImageRejected):
        process_upload(buffer.getvalue(), filename="bomb.png")


def test_exif_is_stripped_including_gps():
    original = _jpeg_with_gps()
    assert Image.open(io.BytesIO(original)).getexif(), "fixture must carry EXIF"

    result = process_upload(original, filename="holiday.jpg")

    assert not Image.open(io.BytesIO(result.data)).getexif()


def test_derivatives_are_generated_smaller_than_the_original():
    result = process_upload(_png(2000, 1500), filename="big.png")

    sizes = derivatives(result)

    assert set(sizes) == {"thumb", "card", "full"}
    assert Image.open(io.BytesIO(sizes["thumb"])).width < Image.open(io.BytesIO(sizes["card"])).width
    assert Image.open(io.BytesIO(sizes["card"])).width < 2000


def test_a_derivative_is_never_upscaled():
    """A 100px image asked for a 1600px 'full' must stay 100px. Upscaling
    invents detail and makes the stored dimensions a lie."""
    result = process_upload(_png(100, 80), filename="tiny.png")

    sizes = derivatives(result)

    assert Image.open(io.BytesIO(sizes["full"])).width == 100


def test_the_content_hash_is_stable_for_identical_pixels():
    """Content addressing: the same photo uploaded twice must land on the same
    key rather than filling the volume with duplicates."""
    first = process_upload(_png(300, 200), filename="a.png")
    second = process_upload(_png(300, 200), filename="b.png")

    assert first.digest == second.digest
