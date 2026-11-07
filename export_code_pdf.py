import subprocess
import os
import textwrap
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Preformatted,
)

OUTPUT = "oss_agent_complete_codebase.pdf"

EXCLUDED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pdf", ".zip", ".sqlite", ".db",
    ".mp3", ".mp4", ".wav", ".pyc",
    ".so", ".dll", ".exe", ".bin",
}


def git_command(*args):
    return subprocess.check_output(
        ["git", *args],
        text=True,
        errors="replace",
    )


def get_committed_files():
    files = git_command(
        "ls-tree", "-r", "--name-only", "HEAD"
    ).splitlines()

    return [
        f for f in files
        if os.path.splitext(f)[1].lower()
        not in EXCLUDED_EXTENSIONS
    ]


def get_file_content(filename):
    try:
        return subprocess.check_output(
            ["git", "show", f"HEAD:{filename}"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return b""


def split_long_lines(text, width=110):
    result = []

    for line in text.splitlines():
        if not line:
            result.append("")
        else:
            result.extend(
                textwrap.wrap(
                    line,
                    width=width,
                    replace_whitespace=False,
                    drop_whitespace=False,
                    break_long_words=True,
                    break_on_hyphens=False,
                ) or [""]
            )

    return result


def main():
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CodeTitle",
        parent=styles["Heading2"],
        fontSize=10,
        leading=13,
        textColor=HexColor("#1F4E79"),
        spaceBefore=8,
        spaceAfter=5,
    )

    code_style = ParagraphStyle(
        "Code",
        fontName="Courier",
        fontSize=6,
        leading=7,
        leftIndent=3,
        rightIndent=3,
        spaceAfter=2,
    )

    doc = SimpleDocTemplate(
        OUTPUT,
        pagesize=A4,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    story = []

    files = get_committed_files()
    commit_hash = git_command("rev-parse", "HEAD").strip()

    story.append(
        Paragraph(
            "OSS-AGENT — COMPLETE CODEBASE",
            styles["Title"],
        )
    )

    story.append(
        Paragraph(
            f"Git commit: {escape(commit_hash)}",
            styles["Normal"],
        )
    )

    story.append(
        Paragraph(
            f"Tracked files: {len(files)}",
            styles["Normal"],
        )
    )

    story.append(Spacer(1, 12))

    included = 0

    for index, filename in enumerate(files, start=1):
        content = get_file_content(filename)

        if b"\x00" in content:
            continue

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue

        story.append(
            Paragraph(
                f"FILE {index} — {escape(filename)}",
                title_style,
            )
        )

        lines = split_long_lines(text)

        # Keep each PDF code block small enough to fit on a page.
        chunk_size = 45

        if not lines:
            lines = [""]

        for start in range(0, len(lines), chunk_size):
            chunk = lines[start:start + chunk_size]

            story.append(
                Preformatted(
                    "\n".join(chunk),
                    code_style,
                )
            )

            story.append(Spacer(1, 4))

        included += 1

        print(f"[{included}/{len(files)}] Exported: {filename}")

    doc.build(story)

    print("\nPDF CREATED SUCCESSFULLY")
    print(f"Output: {OUTPUT}")
    print(f"Files included: {included}")
    print(f"Git commit: {commit_hash}")


if __name__ == "__main__":
    main()
