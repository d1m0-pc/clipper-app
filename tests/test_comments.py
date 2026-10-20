"""Timestamp extraction from comments and the likes-weighted ranking."""

import pytest

from clipper_app.comments import extract_timestamps, find_comment_moments
from clipper_app.models import SOURCE_COMMENTS


class TestExtractTimestamps:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("4:12 I lost it", [252]),
            ("at 0:45 lol", [45]),
            ("12:34", [754]),
            ("1:02:03 best part", [3723]),
            ("10:00:00", [36000]),
            ("75:30 in a long stream", [4530]),
            ("4:12 and again 4:12", [252]),
            ("first 1:00 then 2:30, finally 3:15!", [60, 150, 195]),
            ("(5:05)", [305]),
            ("5:05.", [305]),
            ("Timestamp: 3:21", [201]),
        ],
    )
    def test_finds_timestamps(self, text, expected):
        assert extract_timestamps(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "no timestamps here",
            "",
            "score was 2:1",  # seconds need two digits
            "4:75",  # invalid seconds
            "1:75:00",  # invalid minutes when hours are present
            "meet at 10:30 pm",
            "meet at 10:30pm",
            "around 7:45 AM",
            "around 7:45 a.m.",
            "version 1.2:30",  # part of another number
            "12:345",  # too many digits
            "1:2:3:45",  # not a time
        ],
    )
    def test_ignores_non_timestamps(self, text):
        assert extract_timestamps(text) == []

    def test_respects_video_length(self):
        assert extract_timestamps("2:00 and 9:59 and 20:00", max_seconds=600) == [
            120,
            599,
        ]

    def test_none_text(self):
        assert extract_timestamps(None) == []  # type: ignore[arg-type]


def comment(text, likes=0):
    return {"text": text, "like_count": likes, "parent": "root"}


class TestFindCommentMoments:
    def test_groups_by_minute_and_weights_by_likes(self):
        comments = [
            comment("3:10 haha", likes=10),
            comment("3:40 this part", likes=5),
            comment("7:05 wow", likes=100),
            comment("1:20 ok", likes=0),
        ]
        moments = find_comment_moments(comments, duration=900, top_n=2)
        assert [m.start for m in moments] == [190.0, 425.0]  # sorted by time
        by_start = {m.start: m for m in moments}
        minute_three = by_start[190.0]
        assert minute_three.mentions == 2
        assert minute_three.likes == 15
        assert minute_three.score == 17  # (1 + 10) + (1 + 5)
        assert by_start[425.0].score == 101
        assert all(m.source == SOURCE_COMMENTS for m in moments)

    def test_many_mentions_beat_one_unliked_comment(self):
        comments = [comment("2:00 lol") for _ in range(5)] + [comment("8:00 meh")]
        moments = find_comment_moments(comments, top_n=1)
        assert len(moments) == 1
        assert moments[0].start == 120
        assert moments[0].mentions == 5

    def test_moment_starts_at_most_weighted_second(self):
        comments = [
            comment("5:10", likes=1),
            comment("5:42", likes=50),
            comment("5:42 yes", likes=3),
        ]
        moment = find_comment_moments(comments)[0]
        assert moment.start == 342
        assert moment.end == 342 + 60

    def test_end_is_clamped_to_duration(self):
        moment = find_comment_moments([comment("9:50 ending")], duration=600)[0]
        assert moment.start == 590
        assert moment.end == 600

    def test_chapter_lists_are_ignored(self):
        chapters = "0:00 intro\n1:00 a\n2:00 b\n3:00 c\n4:00 d\n5:00 e"
        moments = find_comment_moments(
            [comment(chapters, likes=5000), comment("6:30 lol")]
        )
        assert [m.start for m in moments] == [390]

    def test_same_minute_counted_once_per_comment(self):
        moments = find_comment_moments([comment("2:10 and 2:20 and 2:30", likes=4)])
        assert len(moments) == 1
        assert moments[0].mentions == 1
        assert moments[0].score == 5

    def test_timestamps_after_duration_are_ignored(self):
        assert find_comment_moments([comment("25:00")], duration=600) == []

    def test_skip_intro(self):
        moments = find_comment_moments(
            [comment("0:30 intro"), comment("3:00 good")], skip_intro=60
        )
        assert [m.start for m in moments] == [180]

    def test_examples_are_most_liked_first_and_limited(self):
        comments = [comment(f"4:0{i} c{i}", likes=i) for i in range(6)]
        moment = find_comment_moments(comments, examples=3)[0]
        assert [e.likes for e in moment.examples] == [5, 4, 3]
        assert moment.examples[0].text == "4:05 c5"

    def test_long_comment_is_shortened_to_one_line(self):
        text = "3:33 " + "very long\ncomment " * 100
        example = find_comment_moments([comment(text)])[0].examples[0]
        assert "\n" not in example.text
        assert len(example.text) <= 300
        assert example.text.endswith("…")

    def test_missing_or_bad_like_counts(self):
        comments = [
            {"text": "1:11"},
            {"text": "1:12", "like_count": None},
            {"text": "1:13", "like_count": "n/a"},
            "not a dict",
        ]
        moment = find_comment_moments(comments)[0]
        assert moment.mentions == 3
        assert moment.score == 3

    def test_top_n_limits_results(self):
        comments = [comment(f"{m}:00", likes=m) for m in range(1, 20)]
        moments = find_comment_moments(comments, top_n=5)
        assert len(moments) == 5
        assert [m.start for m in moments] == [900, 960, 1020, 1080, 1140]

    def test_no_comments(self):
        assert find_comment_moments([]) == []

    def test_overlap_across_minute_boundary_is_one_moment(self):
        # 3:58 and 4:00 fall into different minutes but are the same moment.
        comments = [comment("3:58 lol", 2), comment("4:00 yes", 1), comment("4:01")]
        moments = find_comment_moments(comments)
        assert len(moments) == 1
        moment = moments[0]
        assert (moment.start, moment.end) == (238, 300)
        assert moment.mentions == 3
        assert moment.score == 6

    def test_comment_spanning_two_minutes_is_counted_once(self):
        moments = find_comment_moments([comment("from 3:58 to 4:00", likes=9)])
        assert len(moments) == 1
        assert moments[0].mentions == 1
        assert moments[0].score == 10
        assert len(moments[0].examples) == 1

    def test_merged_moment_is_at_most_twice_as_long(self):
        comments = [comment(t) for t in ("1:30", "2:20", "3:10", "4:05")]
        moments = find_comment_moments(comments, moment_length=60)
        assert [(m.start, m.end) for m in moments] == [(90, 210), (245, 305)]
        assert [m.mentions for m in moments] == [3, 1]

    def test_moments_never_overlap(self):
        comments = [comment(f"{m}:{s:02d}") for m in range(0, 30) for s in (5, 35, 55)]
        moments = find_comment_moments(comments, top_n=50)
        for first, second in zip(moments, moments[1:], strict=False):
            assert first.end <= second.start

    def test_zero_timestamp_is_a_chapter_marker(self):
        assert find_comment_moments([comment("0:00 intro lol", likes=99)]) == []
        moments = find_comment_moments([comment("0:00 and 5:00 lol")])
        assert [m.start for m in moments] == [300]
