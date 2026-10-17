"""Тесты для shared/text.py: экранирование и разбиение длинных сообщений."""
from shared.text import esc, split_message


def test_esc_escapes_html():
    assert esc('<a href="x">hi</a> & co') == '&lt;a href="x"&gt;hi&lt;/a&gt; &amp; co'


def test_esc_none_uses_placeholder():
    assert esc(None) == "—"
    assert esc(None, empty="без ника") == "без ника"


def test_split_message_short_text_is_single_chunk():
    assert split_message("a\nb") == ["a\nb"]


def test_split_message_respects_limit_and_line_boundaries():
    lines = [f"<b>строка {i}</b>" for i in range(500)]
    chunks = split_message("\n".join(lines), limit=200)

    assert all(len(c) <= 200 for c in chunks)
    assert "\n".join(chunks).split("\n") == lines  # ни одна строка не потеряна и не разрезана


def test_split_message_cuts_overlong_line():
    chunks = split_message("x" * 450, limit=200)
    assert [len(c) for c in chunks] == [200, 200, 50]
