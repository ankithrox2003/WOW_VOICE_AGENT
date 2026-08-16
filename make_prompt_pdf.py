"""
Render the live system prompt as a formatted PDF deliverable.

    python make_prompt_pdf.py

Reads SYSTEM_PROMPT straight from system_prompt.py and the runtime settings
from config.py, so the submitted document always matches the prompt the agent
actually ran with. Nothing here is retyped by hand.

The prompt is written in a light markdown dialect - "# " and "## " headings,
pipe tables, "- " bullets, and a few alignment-sensitive blocks - so this
walks the source line by line and maps each construct onto a flowable.
"""
import re
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

import config
from system_prompt import SYSTEM_PROMPT

OUTPUT = "deliverables/WOW_Rohan_System_Prompt.pdf"

INK = colors.HexColor("#1A1A1A")
ACCENT = colors.HexColor("#8C6A3F")      # muted gold, matches the brand tone
SUBTLE = colors.HexColor("#6B6B6B")
RULE = colors.HexColor("#D8CFC0")
PANEL = colors.HexColor("#F7F4EF")

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 2 * cm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

styles = {
    "body": ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.4, leading=13.4,
        textColor=INK, alignment=TA_LEFT, spaceAfter=6,
    ),
    "h1": ParagraphStyle(
        "h1", fontName="Helvetica-Bold", fontSize=13, leading=16,
        textColor=ACCENT, spaceBefore=13, spaceAfter=2,
    ),
    "h2": ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14,
        textColor=INK, spaceBefore=10, spaceAfter=3,
    ),
    "bullet": ParagraphStyle(
        "bullet", fontName="Helvetica", fontSize=9.4, leading=13,
        textColor=INK, leftIndent=13, bulletIndent=3, spaceAfter=3,
    ),
    "mono": ParagraphStyle(
        "mono", fontName="Courier", fontSize=8.2, leading=11,
        textColor=INK, backColor=PANEL, borderPadding=7,
        leftIndent=2, spaceBefore=3, spaceAfter=8,
    ),
    "cell": ParagraphStyle(
        "cell", fontName="Helvetica", fontSize=8.4, leading=11, textColor=INK,
    ),
    "cellhead": ParagraphStyle(
        "cellhead", fontName="Helvetica-Bold", fontSize=8.4, leading=11,
        textColor=colors.white,
    ),
    "title": ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=24, leading=29,
        textColor=INK, spaceAfter=4,
    ),
    "subtitle": ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=12, leading=17,
        textColor=SUBTLE, spaceAfter=20,
    ),
    "note": ParagraphStyle(
        "note", fontName="Helvetica-Oblique", fontSize=9, leading=13,
        textColor=SUBTLE, spaceAfter=6,
    ),
    "example": ParagraphStyle(
        "example", fontName="Helvetica", fontSize=8.8, leading=12.5,
        textColor=INK,
    ),
    "exlabel": ParagraphStyle(
        "exlabel", fontName="Helvetica-Bold", fontSize=8.2, leading=10.5,
    ),
}

GOOD = colors.HexColor("#2F6B44")
BAD = colors.HexColor("#A33A28")
_LABEL_COLOUR = {"CALLER": SUBTLE, "GOOD": GOOD, "BAD": BAD}


def _text(raw: str) -> str:
    """Escape for reportlab, and render `backticks` and **bold** as markup."""
    out = escape(raw)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', out)
    return out


def _is_table_row(line: str) -> bool:
    return line.startswith("|") and line.rstrip().endswith("|")


def _is_table_divider(line: str) -> bool:
    return _is_table_row(line) and set(line.strip("| \n")) <= set("-:| ")


def _split_row(line: str):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _column_widths(rows):
    """Share the page width out in proportion to each column's longest cell."""
    count = max(len(row) for row in rows)
    padded = [row + [""] * (count - len(row)) for row in rows]
    weights = [
        max(len(row[i]) for row in padded) or 1
        for i in range(count)
    ]
    total = sum(weights)
    # Keep any single column from collapsing below something readable.
    floor = 0.13
    shares = [max(w / total, floor) for w in weights]
    scale = sum(shares)
    return [CONTENT_WIDTH * s / scale for s in shares]


def _build_table(rows):
    header, body = rows[0], rows[1:]
    count = max(len(row) for row in rows)
    data = [[Paragraph(_text(c), styles["cellhead"]) for c in header + [""] * (count - len(header))]]
    for row in body:
        data.append([Paragraph(_text(c), styles["cell"]) for c in row + [""] * (count - len(row))])

    table = Table(data, colWidths=_column_widths(rows), hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL]),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


# Blocks whose alignment carries meaning: the "92.4 lakh -> ninety two..."
# number mappings and the aligned "Field : value" fact sheet. These are set in
# monospace so the columns survive; everything else gets reflowed.
# A short label, padded out, then a colon. The length bound keeps ordinary
# prose that happens to contain a colon out of the monospace blocks.
_FIELD_LINE = re.compile(r"^[A-Za-z][\w .()/-]{0,22}\s+: ")

# The CALLER / BAD / GOOD transcript examples, whose quoted text runs across
# several indented continuation lines.
_EXAMPLE_LABEL = re.compile(r"^(CALLER|BAD|GOOD)\b(.*)$")


# The lettered checkpoint list, "  A. INTENT     - Self-use or investment?"
_CHECKPOINT_LINE = re.compile(r"^\s+[A-D]\.\s+[A-Z]{4,}")


def _wants_mono(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _FIELD_LINE.match(line):
        return True
    if _CHECKPOINT_LINE.match(line):
        return True
    if "->" in stripped:
        return True
    return stripped == "[END_CALL]"


def _build_examples(entries):
    """Render a CALLER/BAD/GOOD group as a labelled two-column panel."""
    rows = []
    for label, qualifier, text in entries:
        colour = _LABEL_COLOUR[label]
        head = f'<font color="{colour}"><b>{label}</b></font>'
        if qualifier:
            head += f'<br/><font color="{SUBTLE}" size="7">{_text(qualifier)}</font>'
        rows.append([
            Paragraph(head, styles["exlabel"]),
            Paragraph(_text(text), styles["example"]),
        ])

    panel = Table(
        rows,
        colWidths=[CONTENT_WIDTH * 0.15, CONTENT_WIDTH * 0.85],
        hAlign="LEFT",
    )
    panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBEFORE", (0, 0), (0, -1), 2, ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return panel


def parse(prompt: str):
    """Turn the prompt's markdown dialect into reportlab flowables."""
    flowables = []
    lines = prompt.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if _is_table_row(line):
            rows = []
            while i < len(lines) and _is_table_row(lines[i]):
                if not _is_table_divider(lines[i]):
                    rows.append(_split_row(lines[i]))
                i += 1
            if rows:
                flowables.append(Spacer(1, 3))
                flowables.append(_build_table(rows))
                flowables.append(Spacer(1, 9))
            continue

        if stripped.startswith("## "):
            flowables.append(Paragraph(_text(stripped[3:]), styles["h2"]))
            i += 1
            continue

        if stripped.startswith("# "):
            flowables.append(Paragraph(_text(stripped[2:]).upper(), styles["h1"]))
            flowables.append(_HorizontalRule())
            i += 1
            continue

        if _EXAMPLE_LABEL.match(stripped) and not _wants_mono(line):
            entries = []
            while i < len(lines):
                match = _EXAMPLE_LABEL.match(lines[i].strip())
                if not match:
                    # A blank line inside the group is fine; anything else ends it.
                    if not lines[i].strip() and i + 1 < len(lines) and _EXAMPLE_LABEL.match(lines[i + 1].strip()):
                        i += 1
                        continue
                    break
                label, remainder = match.group(1), match.group(2).strip()
                # Anything before the opening quote is an aside about the
                # example, e.g. 'BAD  (too long, assumes facts):' or
                # 'GOOD pitch (two sentences, not a list):'.
                if '"' in remainder:
                    split_at = remainder.index('"')
                    qualifier, inline = remainder[:split_at], remainder[split_at:]
                else:
                    qualifier, inline = remainder, ""
                qualifier = qualifier.strip().rstrip(":").strip()
                inline = inline.strip()
                i += 1

                parts = [inline] if inline else []
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                    parts.append(lines[i].strip())
                    i += 1
                entries.append((label, qualifier, " ".join(parts)))

            flowables.append(KeepTogether([_build_examples(entries), Spacer(1, 8)]))
            continue

        if _wants_mono(line):
            block = []
            while i < len(lines) and (_wants_mono(lines[i]) or (block and lines[i].startswith("  "))):
                block.append(lines[i].rstrip())
                i += 1
            flowables.append(Preformatted("\n".join(block), styles["mono"]))
            continue

        if stripped.startswith("- "):
            block = [stripped[2:]]
            i += 1
            # Continuation lines of a bullet are indented under it.
            while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() and not lines[i].strip().startswith("- "):
                block.append(lines[i].strip())
                i += 1
            flowables.append(Paragraph(_text(" ".join(block)), styles["bullet"], bulletText="\u2022"))
            continue

        # Ordinary paragraph: gather until a blank line or a new construct.
        block = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip() or nxt.strip().startswith(("#", "- ", "|")) or _wants_mono(nxt):
                break
            block.append(nxt.strip())
            i += 1
        flowables.append(Paragraph(_text(" ".join(block)), styles["body"]))

    return flowables


class _HorizontalRule(Table):
    """A thin rule under each section heading."""

    def __init__(self):
        super().__init__([[""]], colWidths=[CONTENT_WIDTH], rowHeights=[1.2])
        self.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))


def cover():
    """Title block plus the exact runtime configuration behind this prompt."""
    voice = config.TTS_VOICE
    settings = [
        ("Agent", "Rohan - Senior Property Consultant, DivyaSree Developers"),
        ("Purpose", "Outbound lead qualification for Whispers of the Wind"),
        ("Language model", f"{config.LLM_MODEL} via Ollama, {config.LLM_NUM_CTX} token context"),
        ("Speech to text", f"faster-whisper '{config.STT_MODEL_SIZE}', language auto-detected"),
        ("Text to speech", f"{voice}, with fallback to {', '.join(config.TTS_FALLBACK_CHAIN)}"),
        ("Turn taking", f"WebRTC VAD, {config.SILENCE_TIMEOUT_MS} ms silence ends a turn"),
        ("Reply ceiling", f"{config.LLM_MAX_TOKENS} tokens, enforced as 2 sentences / 40 words"),
        ("Checkpoints", "Intent, Geography, Budget, Timeline - tracked in code, not by the model"),
    ]

    rows = [
        [Paragraph(f"<b>{_text(k)}</b>", styles["cell"]), Paragraph(_text(v), styles["cell"])]
        for k, v in settings
    ]
    table = Table(rows, colWidths=[CONTENT_WIDTH * 0.26, CONTENT_WIDTH * 0.74], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]))

    return [
        Spacer(1, 1.6 * cm),
        Paragraph("Whispers of the Wind", styles["title"]),
        Paragraph("Outbound Voice Agent &mdash; System Prompt", styles["subtitle"]),
        _HorizontalRule(),
        Spacer(1, 0.7 * cm),
        Paragraph(
            "This is the complete, unedited system prompt used by the voice agent. "
            "It is generated directly from the running source, so it cannot drift "
            "from the instructions the agent was actually given.",
            styles["body"],
        ),
        Spacer(1, 0.4 * cm),
        table,
        Spacer(1, 0.5 * cm),
        Paragraph(f"Generated {date.today():%d %B %Y}", styles["note"]),
        PageBreak(),
    ]


def _decorate(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(SUBTLE)
    canvas.drawString(MARGIN, 1.15 * cm, "Whispers of the Wind - Voice Agent System Prompt")
    canvas.drawRightString(PAGE_WIDTH - MARGIN, 1.15 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN, 1.5 * cm, PAGE_WIDTH - MARGIN, 1.5 * cm)
    canvas.restoreState()


def build(path: str = OUTPUT):
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        path,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=2.2 * cm,
        title="Whispers of the Wind - Voice Agent System Prompt",
        author="Rohan voice agent",
        subject="System prompt for the WOW outbound lead-qualification agent",
    )
    frame = Frame(MARGIN, 2.2 * cm, CONTENT_WIDTH, PAGE_HEIGHT - MARGIN - 2.2 * cm, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_decorate)])

    doc.build(cover() + parse(SYSTEM_PROMPT))
    return path


if __name__ == "__main__":
    written = build()
    words = len(SYSTEM_PROMPT.split())
    print(f"Wrote {written}  ({words} words of prompt, {len(SYSTEM_PROMPT)} characters)")
