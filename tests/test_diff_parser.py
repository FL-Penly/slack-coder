"""
Unit tests for core/diff_parser.py
"""

import pytest
from core.diff_parser import (
    parse_unified_diff,
    format_diff_summary,
    format_diff_for_slack,
    format_diff_as_rich_text_blocks,
    FileDiff,
    DiffHunk,
)


# Sample diff outputs for testing
SIMPLE_DIFF = """diff --git a/hello.py b/hello.py
index 1234567..abcdefg 100644
--- a/hello.py
+++ b/hello.py
@@ -1,3 +1,4 @@
 def hello():
-    print("Hello")
+    print("Hello, World!")
+    return True
"""

NEW_FILE_DIFF = """diff --git a/new_file.py b/new_file.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,5 @@
+def new_function():
+    pass
+
+if __name__ == "__main__":
+    new_function()
"""

DELETED_FILE_DIFF = """diff --git a/old_file.py b/old_file.py
deleted file mode 100644
index 1234567..0000000
--- a/old_file.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def old_function():
-    pass
-
"""

BINARY_FILE_DIFF = """diff --git a/image.png b/image.png
Binary files a/image.png and b/image.png differ
"""

MULTI_FILE_DIFF = """diff --git a/file1.py b/file1.py
index 1234567..abcdefg 100644
--- a/file1.py
+++ b/file1.py
@@ -1,2 +1,2 @@
-old_line = 1
+new_line = 1
 unchanged = 2
diff --git a/file2.py b/file2.py
index 1234567..abcdefg 100644
--- a/file2.py
+++ b/file2.py
@@ -5,3 +5,4 @@
 def func():
     pass
+    return None
"""

MULTI_HUNK_DIFF = """diff --git a/large_file.py b/large_file.py
index 1234567..abcdefg 100644
--- a/large_file.py
+++ b/large_file.py
@@ -10,3 +10,3 @@
 def first_func():
-    old_code()
+    new_code()
@@ -50,4 +50,5 @@
 def second_func():
     pass
+    # Added comment
+    return True
"""


class TestParseUnifiedDiff:
    """Tests for parse_unified_diff function."""

    def test_empty_input(self):
        """Should return empty list for empty input."""
        assert parse_unified_diff("") == []
        assert parse_unified_diff("   ") == []
        assert parse_unified_diff(None) == []

    def test_simple_diff(self):
        """Should parse a simple single-file diff."""
        files = parse_unified_diff(SIMPLE_DIFF)

        assert len(files) == 1
        assert files[0].old_path == "hello.py"
        assert files[0].new_path == "hello.py"
        assert files[0].is_new_file is False
        assert files[0].is_deleted_file is False
        assert files[0].is_binary is False
        assert len(files[0].hunks) == 1

        hunk = files[0].hunks[0]
        assert hunk.old_start == 1
        assert hunk.old_count == 3
        assert hunk.new_start == 1
        assert hunk.new_count == 4

        # Check changes
        changes = hunk.changes
        assert (" ", "def hello():") in changes
        assert ("-", '    print("Hello")') in changes
        assert ("+", '    print("Hello, World!")') in changes
        assert ("+", "    return True") in changes

    def test_new_file_diff(self):
        """Should detect new file."""
        files = parse_unified_diff(NEW_FILE_DIFF)

        assert len(files) == 1
        assert files[0].is_new_file is True
        assert files[0].is_deleted_file is False
        assert files[0].new_path == "new_file.py"

    def test_deleted_file_diff(self):
        """Should detect deleted file."""
        files = parse_unified_diff(DELETED_FILE_DIFF)

        assert len(files) == 1
        assert files[0].is_deleted_file is True
        assert files[0].is_new_file is False
        assert files[0].old_path == "old_file.py"

    def test_binary_file_diff(self):
        """Should detect binary file."""
        files = parse_unified_diff(BINARY_FILE_DIFF)

        assert len(files) == 1
        assert files[0].is_binary is True
        assert files[0].new_path == "image.png"

    def test_multi_file_diff(self):
        """Should parse multiple files."""
        files = parse_unified_diff(MULTI_FILE_DIFF)

        assert len(files) == 2
        assert files[0].new_path == "file1.py"
        assert files[1].new_path == "file2.py"

    def test_multi_hunk_diff(self):
        """Should parse multiple hunks in one file."""
        files = parse_unified_diff(MULTI_HUNK_DIFF)

        assert len(files) == 1
        assert len(files[0].hunks) == 2

        assert files[0].hunks[0].old_start == 10
        assert files[0].hunks[1].old_start == 50


class TestFormatDiffSummary:
    """Tests for format_diff_summary function."""

    def test_empty_files(self):
        """Should return '没有变更' for empty list."""
        assert format_diff_summary([]) == "没有变更"

    def test_simple_summary(self):
        """Should generate correct summary."""
        files = parse_unified_diff(SIMPLE_DIFF)
        summary = format_diff_summary(files)

        assert "1 个文件变更" in summary
        assert "2 处新增(+)" in summary
        assert "1 处删除(-)" in summary

    def test_multi_file_summary(self):
        """Should count multiple files."""
        files = parse_unified_diff(MULTI_FILE_DIFF)
        summary = format_diff_summary(files)

        assert "2 个文件变更" in summary

    def test_insertions_only(self):
        """Should handle insertions only."""
        files = parse_unified_diff(NEW_FILE_DIFF)
        summary = format_diff_summary(files)

        assert "新增(+)" in summary
        assert "删除(-)" not in summary

    def test_deletions_only(self):
        """Should handle deletions only."""
        files = parse_unified_diff(DELETED_FILE_DIFF)
        summary = format_diff_summary(files)

        assert "删除(-)" in summary
        assert "新增(+)" not in summary


class TestFormatDiffForSlack:
    """Tests for format_diff_for_slack function."""

    def test_empty_files(self):
        """Should return no changes message."""
        result = format_diff_for_slack([])
        assert "没有检测到代码变更" in result

    def test_simple_format(self):
        """Should format simple diff."""
        files = parse_unified_diff(SIMPLE_DIFF)
        result = format_diff_for_slack(files)

        assert "hello.py" in result
        assert "📄" in result

    def test_new_file_icon(self):
        """Should show new file icon."""
        files = parse_unified_diff(NEW_FILE_DIFF)
        result = format_diff_for_slack(files)

        assert "🆕" in result
        assert "新文件" in result

    def test_deleted_file_icon(self):
        """Should show deleted file icon."""
        files = parse_unified_diff(DELETED_FILE_DIFF)
        result = format_diff_for_slack(files)

        assert "🗑️" in result
        assert "已删除" in result

    def test_binary_file_icon(self):
        """Should show binary file icon."""
        files = parse_unified_diff(BINARY_FILE_DIFF)
        result = format_diff_for_slack(files)

        assert "📦" in result
        assert "二进制" in result

    def test_max_files_limit(self):
        """Should respect max_files limit."""
        # Create a diff with many files
        many_files_diff = ""
        for i in range(10):
            many_files_diff += f"""diff --git a/file{i}.py b/file{i}.py
index 1234567..abcdefg 100644
--- a/file{i}.py
+++ b/file{i}.py
@@ -1,1 +1,1 @@
-old
+new
"""
        files = parse_unified_diff(many_files_diff)
        result = format_diff_for_slack(files, max_files=3)

        assert "还有 7 个文件未显示" in result

    def test_max_changes_limit(self):
        """Should respect max_changes_per_file limit."""
        # Create a diff with many changes
        many_changes_diff = """diff --git a/big.py b/big.py
index 1234567..abcdefg 100644
--- a/big.py
+++ b/big.py
@@ -1,20 +1,20 @@
"""
        for i in range(20):
            many_changes_diff += f"-old_line_{i}\n+new_line_{i}\n"

        files = parse_unified_diff(many_changes_diff)
        result = format_diff_for_slack(files, max_changes_per_file=5)

        assert "还有" in result and "处变更未显示" in result


class TestFormatDiffAsRichTextBlocks:
    """Tests for format_diff_as_rich_text_blocks function."""

    def test_empty_files(self):
        """Should return no changes block."""
        blocks = format_diff_as_rich_text_blocks([])

        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert "没有未提交的更改" in blocks[0]["text"]["text"]

    def test_simple_blocks(self):
        """Should generate blocks for simple diff."""
        files = parse_unified_diff(SIMPLE_DIFF)
        blocks = format_diff_as_rich_text_blocks(files)

        # Should have section for filename and rich_text for changes
        assert any(b["type"] == "section" for b in blocks)
        assert any(b["type"] == "rich_text" for b in blocks)

    def test_rich_text_structure(self):
        """Should have correct rich_text structure."""
        files = parse_unified_diff(SIMPLE_DIFF)
        blocks = format_diff_as_rich_text_blocks(files)

        rich_text_blocks = [b for b in blocks if b["type"] == "rich_text"]
        assert len(rich_text_blocks) > 0

        # Check structure of rich_text block
        rt_block = rich_text_blocks[0]
        assert "elements" in rt_block

        # Each element should be a rich_text_section
        for element in rt_block["elements"]:
            assert element["type"] == "rich_text_section"
            assert "elements" in element

    def test_deletion_addition_markers(self):
        """Should use correct emoji markers."""
        files = parse_unified_diff(SIMPLE_DIFF)
        blocks = format_diff_as_rich_text_blocks(files)

        # Convert to string for easy checking
        blocks_str = str(blocks)

        assert "🔴" in blocks_str  # Deletion marker
        assert "🟢" in blocks_str  # Addition marker

    def test_code_style(self):
        """Should apply code style to diff lines."""
        files = parse_unified_diff(SIMPLE_DIFF)
        blocks = format_diff_as_rich_text_blocks(files)

        rich_text_blocks = [b for b in blocks if b["type"] == "rich_text"]

        # Find elements with code style
        has_code_style = False
        for rt_block in rich_text_blocks:
            for section in rt_block["elements"]:
                for elem in section["elements"]:
                    if elem.get("style", {}).get("code"):
                        has_code_style = True
                        break

        assert has_code_style

    def test_max_files_limit(self):
        """Should respect max_files limit."""
        many_files_diff = ""
        for i in range(10):
            many_files_diff += f"""diff --git a/file{i}.py b/file{i}.py
index 1234567..abcdefg 100644
--- a/file{i}.py
+++ b/file{i}.py
@@ -1,1 +1,1 @@
-old
+new
"""
        files = parse_unified_diff(many_files_diff)
        blocks = format_diff_as_rich_text_blocks(files, max_files=3)

        # Should have context block with remaining files message
        context_blocks = [b for b in blocks if b["type"] == "context"]
        assert any("还有 7 个文件未显示" in str(b) for b in context_blocks)

    def test_binary_file_handling(self):
        """Should handle binary files correctly."""
        files = parse_unified_diff(BINARY_FILE_DIFF)
        blocks = format_diff_as_rich_text_blocks(files)

        blocks_str = str(blocks)
        assert "📦" in blocks_str
        assert "二进制" in blocks_str

    def test_max_blocks_limit(self):
        """Should respect max_blocks limit to prevent Slack Modal overflow."""
        many_files_diff = ""
        for i in range(20):
            many_files_diff += f"""diff --git a/file{i}.py b/file{i}.py
index 1234567..abcdefg 100644
--- a/file{i}.py
+++ b/file{i}.py
@@ -1,10 +1,10 @@
-old_line_1
-old_line_2
-old_line_3
+new_line_1
+new_line_2
+new_line_3
"""
        files = parse_unified_diff(many_files_diff)
        blocks = format_diff_as_rich_text_blocks(files, max_files=20, max_blocks=15)

        assert len(blocks) <= 15
        context_blocks = [b for b in blocks if b["type"] == "context"]
        assert any(
            "还有" in str(b) and "个文件未显示" in str(b) for b in context_blocks
        )


class TestTruncateLine:
    """Tests for _truncate_line helper function."""

    def test_short_line(self):
        """Should not truncate short lines."""
        from core.diff_parser import _truncate_line

        result = _truncate_line("short", 20)
        assert result == "short"

    def test_long_line(self):
        """Should truncate long lines with ellipsis."""
        from core.diff_parser import _truncate_line

        long_line = "a" * 100
        result = _truncate_line(long_line, 20)

        assert len(result) == 20
        assert result.endswith("...")

    def test_empty_line(self):
        """Should return space for empty line."""
        from core.diff_parser import _truncate_line

        assert _truncate_line("", 20) == " "
        assert _truncate_line("   ", 20) == " "

    def test_backtick_replacement(self):
        """Should replace backticks with single quotes."""
        from core.diff_parser import _truncate_line

        result = _truncate_line("code with `backticks`", 50)
        assert "`" not in result
        assert "'" in result


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_malformed_diff_header(self):
        """Should handle malformed diff header."""
        malformed = """diff --git malformed
--- a/file.py
+++ b/file.py
@@ -1,1 +1,1 @@
-old
+new
"""
        files = parse_unified_diff(malformed)
        # Should still parse something
        assert len(files) >= 0

    def test_hunk_without_count(self):
        """Should handle hunk header without count (defaults to 1)."""
        single_line_diff = """diff --git a/file.py b/file.py
index 1234567..abcdefg 100644
--- a/file.py
+++ b/file.py
@@ -5 +5 @@
-old
+new
"""
        files = parse_unified_diff(single_line_diff)

        assert len(files) == 1
        assert len(files[0].hunks) == 1
        assert files[0].hunks[0].old_count == 1
        assert files[0].hunks[0].new_count == 1

    def test_unicode_content(self):
        """Should handle unicode content."""
        unicode_diff = """diff --git a/unicode.py b/unicode.py
index 1234567..abcdefg 100644
--- a/unicode.py
+++ b/unicode.py
@@ -1,1 +1,1 @@
-print("你好")
+print("世界")
"""
        files = parse_unified_diff(unicode_diff)

        assert len(files) == 1
        changes = files[0].hunks[0].changes
        assert any("你好" in c[1] for c in changes)
        assert any("世界" in c[1] for c in changes)

    def test_special_characters_in_path(self):
        """Should handle special characters in file path."""
        special_path_diff = """diff --git a/path with spaces/file.py b/path with spaces/file.py
index 1234567..abcdefg 100644
--- a/path with spaces/file.py
+++ b/path with spaces/file.py
@@ -1,1 +1,1 @@
-old
+new
"""
        files = parse_unified_diff(special_path_diff)

        assert len(files) == 1
        assert "path with spaces" in files[0].new_path
