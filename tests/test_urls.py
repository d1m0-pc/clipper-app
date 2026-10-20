"""Recognizing video, channel and playlist links."""

import pytest

from clipper_app.urls import KIND_CHANNEL, KIND_PLAYLIST, KIND_VIDEO, parse_youtube_link

VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "text",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2",
        "youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ?feature=share",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",
        '"https://www.youtube.com/watch?v=dQw4w9WgXcQ"',
        "dQw4w9WgXcQ",
    ],
)
def test_video_links(text):
    link = parse_youtube_link(text)
    assert link.kind == KIND_VIDEO
    assert link.video_id == "dQw4w9WgXcQ"
    assert link.url == VIDEO
    assert not link.is_list


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://youtube.com/@waveform", "https://www.youtube.com/@waveform/videos"),
        (
            "https://www.youtube.com/@waveform/",
            "https://www.youtube.com/@waveform/videos",
        ),
        (
            "https://www.youtube.com/@waveform/featured",
            "https://www.youtube.com/@waveform/videos",
        ),
        (
            "https://www.youtube.com/@waveform/videos",
            "https://www.youtube.com/@waveform/videos",
        ),
        (
            "https://www.youtube.com/@waveform/shorts",
            "https://www.youtube.com/@waveform/shorts",
        ),
        (
            "https://www.youtube.com/@waveform/streams",
            "https://www.youtube.com/@waveform/streams",
        ),
        ("youtube.com/@waveform", "https://www.youtube.com/@waveform/videos"),
        ("@waveform", "https://www.youtube.com/@waveform/videos"),
        (
            "https://www.youtube.com/channel/UCBJycsmduvYEL83R_U4JriQ",
            "https://www.youtube.com/channel/UCBJycsmduvYEL83R_U4JriQ/videos",
        ),
        ("https://www.youtube.com/c/mkbhd", "https://www.youtube.com/c/mkbhd/videos"),
        (
            "https://www.youtube.com/user/marquesbrownlee/about",
            "https://www.youtube.com/user/marquesbrownlee/videos",
        ),
    ],
)
def test_channel_links(text, expected):
    link = parse_youtube_link(text)
    assert link.kind == KIND_CHANNEL
    assert link.url == expected
    assert link.is_list


def test_unicode_handle_is_quoted():
    link = parse_youtube_link("https://www.youtube.com/@Šljivić")
    assert link.kind == KIND_CHANNEL
    assert link.url.startswith("https://www.youtube.com/@%C5%A0")


def test_playlist_link():
    link = parse_youtube_link("https://www.youtube.com/playlist?list=PLabc123")
    assert link.kind == KIND_PLAYLIST
    assert link.url == "https://www.youtube.com/playlist?list=PLabc123"
    assert link.is_list


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "https://vimeo.com/123",
        "https://www.youtube.com/watch?v=short",
        "https://youtu.be/",
        "https://www.youtube.com/",
        "https://www.youtube.com/results?search_query=cats",
        "hello world",
    ],
)
def test_invalid_links_raise_with_serbian_message(text):
    with pytest.raises(ValueError) as error:
        parse_youtube_link(text)
    assert "Example" in str(error.value)
