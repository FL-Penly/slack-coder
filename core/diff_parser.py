"""
Diff parser and formatter for Slack-friendly display.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from modules.i18n import t


@dataclass
class DiffHunk:
    """A single hunk of changes in a file."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    changes: List[tuple] = field(default_factory=list)


@dataclass
class FileDiff:
    """All changes in a single file."""

    old_path: str
    new_path: str
    hunks: List[DiffHunk] = field(default_factory=list)
    is_new_file: bool = False
    is_deleted_file: bool = False
    is_binary: bool = False


def parse_unified_diff(diff_output: str) -> List[FileDiff]:
    """Parse unified diff output into structured FileDiff objects."""
    if not diff_output or not diff_output.strip():
        return []

    files: List[FileDiff] = []
    current_file: Optional[FileDiff] = None
    current_hunk: Optional[DiffHunk] = None

    lines = diff_output.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("diff --git"):
            if current_file is not None:
                if current_hunk is not None:
                    current_file.hunks.append(current_hunk)
                files.append(current_file)

            match = re.match(r"diff --git a/(.*) b/(.*)", line)
            if match:
                current_file = FileDiff(
                    old_path=match.group(1), new_path=match.group(2)
                )
            else:
                current_file = FileDiff(old_path="unknown", new_path="unknown")
            current_hunk = None
            i += 1
            continue

        if current_file is not None:
            if line.startswith("new file mode"):
                current_file.is_new_file = True
                i += 1
                continue
            if line.startswith("deleted file mode"):
                current_file.is_deleted_file = True
                i += 1
                continue
            if line.startswith("Binary files"):
                current_file.is_binary = True
                i += 1
                continue

        # @@ -old_start,old_count +new_start,new_count @@
        hunk_match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if hunk_match and current_file is not None:
            if current_hunk is not None:
                current_file.hunks.append(current_hunk)

            current_hunk = DiffHunk(
                old_start=int(hunk_match.group(1)),
                old_count=int(hunk_match.group(2) or 1),
                new_start=int(hunk_match.group(3)),
                new_count=int(hunk_match.group(4) or 1),
                changes=[],
            )
            i += 1
            continue

        if current_hunk is not None:
            if line.startswith("+") and not line.startswith("+++"):
                current_hunk.changes.append(("+", line[1:]))
            elif line.startswith("-") and not line.startswith("---"):
                current_hunk.changes.append(("-", line[1:]))
            elif line.startswith(" "):
                current_hunk.changes.append((" ", line[1:]))

        i += 1

    if current_file is not None:
        if current_hunk is not None:
            current_file.hunks.append(current_hunk)
        files.append(current_file)

    return files


def _truncate_line(line: str, max_length: int) -> str:
    line = line.strip().replace("`", "'")
    if not line:
        return " "
    if len(line) > max_length:
        return line[: max_length - 3] + "..."
    return line


def _output_paired_changes(
    output_parts: List[str],
    deletions: List[str],
    additions: List[str],
    changes_shown: int,
    max_changes: int,
) -> int:
    max_pairs = max(len(deletions), len(additions))

    for j in range(max_pairs):
        if changes_shown >= max_changes:
            break

        if j < len(deletions):
            output_parts.append(f"  ➖ `{_truncate_line(deletions[j], 60)}`")
        if j < len(additions):
            output_parts.append(f"  ➕ `{_truncate_line(additions[j], 60)}`")

        changes_shown += 1

    return changes_shown


def format_diff_for_slack(
    files: List[FileDiff], max_changes_per_file: int = 10, max_files: int = 5
) -> str:
    """Format parsed diff into Slack-friendly up-down comparison format."""
    if not files:
        return t("diff.no_changes")

    output_parts = []
    files_shown = 0

    for file_diff in files:
        if files_shown >= max_files:
            remaining = len(files) - max_files
            output_parts.append(f"\n_... 还有 {remaining} 个文件未显示_")
            break

        files_shown += 1

        if file_diff.is_new_file:
            icon, status = "🆕", t("diff.new_file")
        elif file_diff.is_deleted_file:
            icon, status = "🗑️", t("diff.deleted_file")
        elif file_diff.is_binary:
            icon, status = "📦", t("diff.binary_file")
        else:
            icon, status = "📄", ""

        output_parts.append(f"\n{icon} *{file_diff.new_path}* {status}")

        if file_diff.is_binary:
            output_parts.append(f"  _{t('diff.binary_changed')}_")
            continue

        changes_shown = 0
        for hunk in file_diff.hunks:
            if changes_shown >= max_changes_per_file:
                break

            deletions = []
            additions = []

            for change_type, content in hunk.changes:
                if change_type == "-":
                    if additions:
                        changes_shown = _output_paired_changes(
                            output_parts,
                            deletions,
                            additions,
                            changes_shown,
                            max_changes_per_file,
                        )
                        deletions, additions = [], []
                    deletions.append(content)
                elif change_type == "+":
                    additions.append(content)
                else:
                    if deletions or additions:
                        changes_shown = _output_paired_changes(
                            output_parts,
                            deletions,
                            additions,
                            changes_shown,
                            max_changes_per_file,
                        )
                        deletions, additions = [], []

            if deletions or additions:
                changes_shown = _output_paired_changes(
                    output_parts,
                    deletions,
                    additions,
                    changes_shown,
                    max_changes_per_file,
                )

        total_changes = sum(
            len([c for c in h.changes if c[0] != " "]) for h in file_diff.hunks
        )
        if total_changes > max_changes_per_file:
            remaining = total_changes - max_changes_per_file
            output_parts.append(f"  _... 还有 {remaining} 处变更未显示_")

    return "\n".join(output_parts)


def format_diff_summary(files: List[FileDiff]) -> str:
    """Generate a brief summary like '3 files changed, 10 insertions(+), 5 deletions(-)'."""
    if not files:
        return t("diff.no_changes")

    total_insertions = 0
    total_deletions = 0

    for file_diff in files:
        for hunk in file_diff.hunks:
            for change_type, _ in hunk.changes:
                if change_type == "+":
                    total_insertions += 1
                elif change_type == "-":
                    total_deletions += 1

    parts = [t("diff.files_changed", count=len(files))]
    if total_insertions > 0:
        parts.append(t("diff.insertions", count=total_insertions))
    if total_deletions > 0:
        parts.append(t("diff.deletions", count=total_deletions))

    return ", ".join(parts)


def format_diff_as_rich_text_blocks(
    files: List[FileDiff],
    max_changes_per_file: int = 8,
    max_files: int = 5,
    max_blocks: int = 80,
) -> List[dict]:
    if not files:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"✅ {t('diff.no_changes')}"},
            }
        ]

    blocks = []
    files_shown = 0

    for file_diff in files:
        if files_shown >= max_files or len(blocks) >= max_blocks - 5:
            remaining = len(files) - files_shown
            if remaining > 0:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"_... 还有 {remaining} 个文件未显示_",
                            }
                        ],
                    }
                )
            break

        files_shown += 1

        if file_diff.is_new_file:
            icon, status = "🆕", f" {t('diff.new_file')}"
        elif file_diff.is_deleted_file:
            icon, status = "🗑️", f" {t('diff.deleted_file')}"
        elif file_diff.is_binary:
            icon, status = "📦", f" {t('diff.binary_file')}"
        else:
            icon, status = "📄", ""

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{icon} *{file_diff.new_path}*{status}",
                },
            }
        )

        if file_diff.is_binary:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"_{t('diff.binary_changed')}_"}
                    ],
                }
            )
            continue

        rich_text_elements = []
        changes_shown = 0

        for hunk in file_diff.hunks:
            if changes_shown >= max_changes_per_file:
                break

            deletions = []
            additions = []

            for change_type, content in hunk.changes:
                if change_type == "-":
                    if additions:
                        changes_shown = _add_rich_text_changes(
                            rich_text_elements,
                            deletions,
                            additions,
                            changes_shown,
                            max_changes_per_file,
                        )
                        deletions, additions = [], []
                    deletions.append(content)
                elif change_type == "+":
                    additions.append(content)
                else:
                    if deletions or additions:
                        changes_shown = _add_rich_text_changes(
                            rich_text_elements,
                            deletions,
                            additions,
                            changes_shown,
                            max_changes_per_file,
                        )
                        deletions, additions = [], []

            if deletions or additions:
                changes_shown = _add_rich_text_changes(
                    rich_text_elements,
                    deletions,
                    additions,
                    changes_shown,
                    max_changes_per_file,
                )

        if rich_text_elements:
            blocks.append({"type": "rich_text", "elements": rich_text_elements})

        total_changes = sum(
            len([c for c in h.changes if c[0] != " "]) for h in file_diff.hunks
        )
        if total_changes > max_changes_per_file:
            remaining = total_changes - max_changes_per_file
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_... 还有 {remaining} 处变更未显示_",
                        }
                    ],
                }
            )

    return blocks


def _add_rich_text_changes(
    elements: List[dict],
    deletions: List[str],
    additions: List[str],
    changes_shown: int,
    max_changes: int,
) -> int:
    max_pairs = max(len(deletions), len(additions))

    for j in range(max_pairs):
        if changes_shown >= max_changes:
            break

        if j < len(deletions):
            del_text = _truncate_line(deletions[j], 65)
            elements.append(
                {
                    "type": "rich_text_section",
                    "elements": [
                        {"type": "text", "text": "🔴 "},
                        {"type": "text", "text": del_text, "style": {"code": True}},
                        {"type": "text", "text": "\n"},
                    ],
                }
            )

        if j < len(additions):
            add_text = _truncate_line(additions[j], 65)
            elements.append(
                {
                    "type": "rich_text_section",
                    "elements": [
                        {"type": "text", "text": "🟢 "},
                        {"type": "text", "text": add_text, "style": {"code": True}},
                        {"type": "text", "text": "\n"},
                    ],
                }
            )

        changes_shown += 1

    return changes_shown
