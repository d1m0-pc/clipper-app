"""Subtitle track selection and json3 transcript parsing."""

import json

import pytest

from clipper_app.models import Cue
from clipper_app.transcript import (
    moment_transcript,
    parse_json3,
    pick_subtitle_track,
    transcript_for_range,
)

MANUAL_JSON3 = {
    "events": [
        {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Hello there."}]},
        {"tStartMs": 3000, "dDurationMs": 2000, "segs": [{"utf8": "General\nKenobi!"}]},
        {"tStartMs": 6000, "dDurationMs": 1000, "segs": [{"utf8": "  "}]},
    ]
}

# Automatic captions: words in separate segs plus "append" events with "\n".
AUTO_JSON3 = {
    "wireMagic": "pb3",
    "events": [
        {"tStartMs": 0, "dDurationMs": 5000, "id": 1, "wpWinPosId": 1},
        {
            "tStartMs": 100,
            "dDurationMs": 4000,
            "segs": [
                {"utf8": "so"},
                {"utf8": " this", "tOffsetMs": 300},
                {"utf8": " is", "tOffsetMs": 600},
            ],
        },
        {"tStartMs": 4100, "dDurationMs": 10, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {
            "tStartMs": 4110,
            "dDurationMs": 3000,
            "segs": [{"utf8": "crazy"}, {"utf8": " [Laughter]", "tOffsetMs": 500}],
        },
    ],
}


def fmt(ext, url=None):
    return {"ext": ext, "url": url or f"https://example.test/{ext}?fmt={ext}"}


class TestParseJson3:
    def test_manual_subtitles(self):
        cues = parse_json3(MANUAL_JSON3)
        assert cues == [
            Cue(1.0, 3.0, "Hello there."),
            Cue(3.0, 5.0, "General Kenobi!"),
        ]

    def test_automatic_captions(self):
        cues = parse_json3(AUTO_JSON3)
        assert [c.text for c in cues] == ["so this is", "crazy [Laughter]"]
        assert cues[0].start == pytest.approx(0.1)

    def test_accepts_text_and_bytes(self):
        text = json.dumps(MANUAL_JSON3)
        assert parse_json3(text) == parse_json3(text.encode("utf-8"))

    def test_sorted_by_time(self):
        data = {
            "events": [
                {"tStartMs": 5000, "segs": [{"utf8": "b"}]},
                {"tStartMs": 1000, "segs": [{"utf8": "a"}]},
            ]
        }
        assert [c.text for c in parse_json3(data)] == ["a", "b"]

    @pytest.mark.parametrize("bad", ["", "   ", "<html>blocked</html>", b"", "[1, 2]"])
    def test_invalid_data_raises_value_error(self, bad):
        with pytest.raises(ValueError):
            parse_json3(bad)

    def test_no_events(self):
        assert parse_json3({"events": []}) == []
        assert parse_json3({}) == []


class TestTranscriptForRange:
    CUES = [
        Cue(0, 4, "intro words"),
        Cue(4, 8, "setup"),
        Cue(8, 12, "the joke"),
        Cue(12, 16, "the joke"),  # repeated line is shown once
        Cue(16, 20, "reaction"),
        Cue(30, 34, "later"),
    ]

    def test_overlapping_cues(self):
        assert transcript_for_range(self.CUES, 5, 17) == "setup the joke reaction"

    def test_cue_touching_start_is_excluded(self):
        assert transcript_for_range(self.CUES, 8, 9) == "the joke"

    def test_nothing_in_range(self):
        assert transcript_for_range(self.CUES, 21, 29) == ""

    def test_moment_transcript_uses_lead_in(self):
        start, text = moment_transcript(self.CUES, 16, 20, lead_in=10)
        assert start == 6
        assert text == "setup the joke reaction"

    def test_lead_in_never_goes_below_zero(self):
        start, text = moment_transcript(self.CUES, 5, 6, lead_in=15)
        assert start == 0
        assert text.startswith("intro words")


class TestPickSubtitleTrack:
    def test_manual_english_preferred(self):
        info = {
            "subtitles": {"en": [fmt("vtt"), fmt("json3")], "de": [fmt("json3")]},
            "automatic_captions": {"en-orig": [fmt("json3")]},
        }
        track = pick_subtitle_track(info)
        assert track is not None
        assert (track.language, track.automatic) == ("en", False)
        assert track.url.endswith("fmt=json3")

    def test_manual_regional_variant(self):
        info = {"subtitles": {"en-US": [fmt("json3")]}, "automatic_captions": {}}
        assert pick_subtitle_track(info).language == "en-US"

    def test_automatic_prefers_original_over_translation(self):
        info = {
            "subtitles": {"sr": [fmt("json3")]},
            "automatic_captions": {"en": [fmt("json3")], "en-orig": [fmt("json3")]},
        }
        track = pick_subtitle_track(info)
        assert (track.language, track.automatic) == ("en-orig", True)
        assert track.kind_label == "automatic"

    def test_automatic_plain_en(self):
        info = {"automatic_captions": {"fr": [fmt("json3")], "en": [fmt("json3")]}}
        assert pick_subtitle_track(info).language == "en"

    def test_adds_json3_parameter_when_missing(self):
        info = {
            "subtitles": {
                "en": [fmt("vtt", "https://example.test/sub?lang=en&fmt=vtt")]
            }
        }
        track = pick_subtitle_track(info)
        assert "fmt=json3" in track.url
        assert "lang=en" in track.url

    def test_keeps_impersonate_hint(self):
        entry = {**fmt("json3"), "impersonate": True}
        track = pick_subtitle_track({"automatic_captions": {"en-orig": [entry]}})
        assert track.impersonate is True

    @pytest.mark.parametrize(
        "info",
        [
            {},
            {"subtitles": None, "automatic_captions": None},
            {"subtitles": {"de": [fmt("json3")]}},
            {"subtitles": {"en": []}},
            {"subtitles": {"en": [{"ext": "json3"}]}},  # no URL
            {"subtitles": {"english": [fmt("json3")]}},  # not a variant of "en"
        ],
    )
    def test_no_english_subtitles(self, info):
        assert pick_subtitle_track(info) is None
