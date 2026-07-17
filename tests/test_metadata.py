from __future__ import annotations

import struct

from mypicsdb3.metadata import image_dimensions, parse_xmp


def test_image_dimensions_for_png_gif_bmp_and_webp() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 640, 480)
    gif = b"GIF89a" + struct.pack("<HH", 320, 240)
    bmp = b"BM" + b"\x00" * 16 + struct.pack("<ii", 800, -600)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x00" * 8 + (1023).to_bytes(3, "little") + (767).to_bytes(3, "little")
    assert image_dimensions(png) == (640, 480)
    assert image_dimensions(gif) == (320, 240)
    assert image_dimensions(bmp) == (800, 600)
    assert image_dimensions(webp) == (1024, 768)


def test_parse_xmp_extracts_date_keywords_rating_location_and_caption() -> None:
    data = b'''prefix<x:xmpmeta xmlns:x="adobe:ns:meta/">
      <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
               xmlns:xmp="http://ns.adobe.com/xap/1.0/"
               xmlns:dc="http://purl.org/dc/elements/1.1/"
               xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
        <rdf:Description xmp:CreateDate="2020-07-17T14:15:16" xmp:Rating="4" photoshop:City="Stockholm">
          <dc:subject><rdf:Bag><rdf:li>Family</rdf:li><rdf:li>Summer</rdf:li></rdf:Bag></dc:subject>
          <dc:description><rdf:Alt><rdf:li>At the lake</rdf:li></rdf:Alt></dc:description>
        </rdf:Description>
      </rdf:RDF>
    </x:xmpmeta>suffix'''
    result = parse_xmp(data)
    assert result["taken_at"] == "2020-07-17 14:15:16"
    assert result["rating"] == 4
    assert result["location"]["city"] == "Stockholm"
    assert "Family" in result["keywords"]
    assert "Summer" in result["keywords"]
    assert result["caption"] == "At the lake"
