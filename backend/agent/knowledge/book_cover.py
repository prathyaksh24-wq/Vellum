"""Cover palette projection matching the supplied bookshelf's color extraction."""
from colorsys import rgb_to_hls, hls_to_rgb
from io import BytesIO
from PIL import Image


def cover_style(content: bytes) -> tuple[float, dict[str, str]]:
    with Image.open(BytesIO(content)) as image:
        if image.width * image.height > 16_000_000:
            raise ValueError("BOOK_COVER_UNAVAILABLE")
        aspect = image.width / image.height
        image = image.convert("RGB")
        image.thumbnail((64, 64))
        pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())
    buckets = {}
    for r, g, b in pixels:
        h, l, s = rgb_to_hls(r / 255, g / 255, b / 255)
        if l > .92 or l < .08: continue
        weight = s * s * (1 - abs(l - .5) * 1.6) + .02
        key = int(h * 36) % 36
        values = buckets.setdefault(key, [0., 0., 0., 0.])
        values[0] += weight
        for i, value in enumerate((r, g, b), 1): values[i] += value * weight
    best = max(buckets.values(), default=[0,0,0,0], key=lambda value: value[0])
    if best[0] < .5:
        rgb = [sum(pixel[i] for pixel in pixels) / len(pixels) / 255 for i in range(3)]
        h, _, _ = rgb_to_hls(*rgb)
        rgb = hls_to_rgb(h, .42, .32)
    else:
        rgb = [value / best[0] / 255 for value in best[1:]]
    h, l, s = rgb_to_hls(*rgb)
    def color(hue, saturation, lightness):
        return "#" + "".join(f"{min(255,max(0,int(value*255+.5))):02x}" for value in hls_to_rgb(hue, lightness, saturation))
    return aspect, {
        "spineColor": color(h, min(.62,s*.9), min(.5,max(.3,l))),
        "accentColor": color((h+.045)%1, min(.68,s+.12), max(.3,l*.82)),
        "inkColor": color(h, min(.35,s*.6), .14),
    }
