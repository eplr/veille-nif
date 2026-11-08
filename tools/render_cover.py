"""Composer la couverture hors pipeline, avec Pillow installé dans un venv.

Les chemins des polices sont explicites pour fonctionner sur macOS et Linux.
Le pipeline de publication téléverse le PNG, sans Pillow ni appel réseau ici.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def render(photo, serif_font, sans_font, output):
    width, height = 3600, 1080
    with Image.open(photo) as source:
        image = ImageOps.fit(source.convert("RGB"), (width, height), centering=(0.5, 0.46)).convert("RGBA")
    # Teinte émeraude et voile léger ; le paysage reste visible.
    image = Image.alpha_composite(image, Image.new("RGBA", image.size, (0, 49, 35, 65)))
    shade = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(shade)
    for x in range(width):
        opacity = int(115 * (1 - x / width) + 25)
        draw.line((x, 0, x, height), fill=(0, 20, 14, opacity))
    image = Image.alpha_composite(image, shade)
    draw = ImageDraw.Draw(image)
    serif = ImageFont.truetype(str(serif_font), 140)
    small = ImageFont.truetype(str(sans_font), 39)
    subtitle = ImageFont.truetype(str(sans_font), 47)
    # Zone centrale préservée pour les recadrages du bandeau Notion.
    def centered(value, y, font, color):
        box = draw.textbbox((0, 0), value, font=font)
        draw.text(((width - box[2]) / 2, y), value, font=font, fill=color,
                  stroke_width=1, stroke_fill=(0, 28, 20, 100))
    centered("N A T U R E   I N   F I N A N C E", 340, small, "#d3ebdb")
    centered("Financer le vivant", 420, serif, "#fffaf0")
    draw.line((1650, 615, 1950, 615), fill="#d4c591", width=3)
    centered("Des idées à l’action", 650, subtitle, "#e4f0e5")
    image = image.convert("RGB")
    image.thumbnail((2560, 768), Image.Resampling.LANCZOS)
    image.save(output, optimize=True)
    if Path(output).stat().st_size > 5 * 1024 * 1024:
        raise ValueError("La couverture doit rester sous 5 Mio pour Notion")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--serif-font", type=Path, required=True)
    parser.add_argument("--sans-font", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.photo, args.serif_font, args.sans_font, args.output)


if __name__ == "__main__":
    main()
