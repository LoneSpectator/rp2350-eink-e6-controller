"""Small Markdown subset: centered #/## titles, bold and six-color spans."""
from content import normalize_text, paint_glyph, text_layout

COLOR_NAMES = {"black": 0, "white": 1, "yellow": 2, "red": 3, "blue": 5, "green": 6}


def span_color(tag):
    attributes = tag[6:-1].strip().split("=", 1)
    if len(attributes) != 2 or attributes[0].strip().lower() != "style":
        raise ValueError('use <span style="color: red"> for Markdown colors')
    style = attributes[1].strip()
    if len(style) < 2 or style[0] not in ("'", '"') or style[-1] != style[0]:
        raise ValueError("Markdown span style must be quoted")
    property_value = style[1:-1].strip().rstrip(";").split(":")
    if len(property_value) != 2 or property_value[0].strip().lower() != "color":
        raise ValueError("Markdown span supports only the color property")
    name = property_value[1].strip().lower()
    if name not in COLOR_NAMES:
        raise ValueError("unsupported Markdown color: " + name)
    return COLOR_NAMES[name]


def inline_runs(source, foreground):
    """Yield text runs, validating tags/markers without building a document tree."""
    start = position = 0
    color, bold = foreground, False
    stack = []
    while position < len(source):
        escaped = source[position] == "\\" and position + 1 < len(source) and (
            source[position + 1] in ("*", "<", "\\"))
        opening = source.startswith("<span ", position)
        closing = source.startswith("</span>", position)
        marker = source.startswith("**", position)
        if not (escaped or opening or closing or marker):
            position += 1
            continue
        if position > start:
            yield source[start:position], color, bold
        if escaped:
            yield source[position + 1:position + 2], color, bold
            position += 2
        elif marker:
            bold = not bold
            position += 2
        elif closing:
            if not stack:
                raise ValueError("Markdown color span has no opening tag")
            color = stack.pop()
            position += 7
        else:
            end = source.find(">", position)
            if end < 0 or len(stack) >= 8:
                raise ValueError("invalid Markdown color span")
            stack.append(color)
            color = span_color(source[position:end + 1])
            position = end + 1
        start = position
    if position > start:
        yield source[start:position], color, bold
    if stack or bold:
        raise ValueError("Markdown ** and color spans must close on the same line")


def source_lines(source):
    start = 0
    while True:
        end = source.find("\n", start)
        if end < 0:
            yield source[start:]
            return
        yield source[start:end]
        start = end + 1


def paint_line(glyphs, width, y, scale, centered, font, canvas, margin):
    if y + font.height * scale > canvas.height - margin:
        raise ValueError("Markdown exceeds one screen; shorten it or reduce text scale")
    x = (canvas.width - width) // 2 if centered else margin
    for advance, bitmap, color, bold in glyphs:
        paint_glyph(font, bitmap, canvas, x, y, scale, color, bold)
        x += advance * scale


def draw_markdown(source, font, canvas, settings):
    margin, base_scale, spacing, foreground, background = text_layout(font, canvas, settings)
    canvas.fill(background)
    available = canvas.width - 2 * margin
    y = margin
    for line in source_lines(normalize_text(source)):
        if not line.strip():
            y += font.height * base_scale // 2 + spacing
            continue
        heading = line.startswith("# ") or line.startswith("## ")
        scale = min(base_scale + 1, 4) if line.startswith("# ") else base_scale
        if heading:
            line = line.split(" ", 1)[1]
        glyphs = []
        advance_width = occupied = 0
        for text, color, marked_bold in inline_runs(line, foreground):
            bold = heading or marked_bold
            for character in text:
                advance, bitmap = font.glyph(character)
                cell = max(advance * scale, font.width * scale + int(bold))
                if cell > available:
                    raise ValueError("Markdown layout has no room for a glyph")
                if advance_width + cell > available:
                    paint_line(glyphs, occupied, y, scale, heading, font, canvas, margin)
                    y += font.height * scale + spacing
                    glyphs = []
                    advance_width = occupied = 0
                occupied = max(occupied, advance_width + cell)
                glyphs.append((advance, bitmap, color, bold))
                advance_width += advance * scale
        if glyphs:
            paint_line(glyphs, occupied, y, scale, heading, font, canvas, margin)
            y += font.height * scale + spacing
