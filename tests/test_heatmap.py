"""Heatmap parsing, intro skipping, top-N selection and segment merging."""

import pytest
from conftest import make_heatmap

from clipper_app.heatmap import (
    find_heatmap_moments,
    merge_adjacent,
    parse_heatmap,
    select_top_segments,
)
from clipper_app.models import SOURCE_HEATMAP, HeatSegment


class TestParseHeatmap:
    def test_parses_and_sorts(self):
        raw = [
            {"start_time": 20.0, "end_time": 30.0, "value": 0.5},
            {"start_time": 0.0, "end_time": 10.0, "value": 1.0},
            {"start_time": 10.0, "end_time": 20.0, "value": 0.25},
        ]
        segments = parse_heatmap(raw)
        assert [s.start for s in segments] == [0.0, 10.0, 20.0]
        assert segments[0] == HeatSegment(0.0, 10.0, 1.0)

    @pytest.mark.parametrize("raw", [None, [], ()])
    def test_empty_input(self, raw):
        assert parse_heatmap(raw) == []

    def test_skips_invalid_entries(self):
        raw = [
            {"start_time": 0, "end_time": 10, "value": 0.4},
            {"start_time": 10},  # missing end
            {"start_time": "x", "end_time": 20, "value": 0.1},  # not a number
            {"start_time": 30, "end_time": 30, "value": 0.1},  # empty range
            {"start_time": -5, "end_time": 5, "value": 0.1},  # negative
            {"start_time": 40, "end_time": 50, "value": float("nan")},
            "garbage",
            None,
        ]
        assert parse_heatmap(raw) == [HeatSegment(0.0, 10.0, 0.4)]

    def test_clamps_values_and_handles_missing_value(self):
        raw = [
            {"start_time": 0, "end_time": 1, "value": 1.7},
            {"start_time": 1, "end_time": 2, "value": -0.3},
            {"start_time": 2, "end_time": 3, "value": None},
        ]
        assert [s.value for s in parse_heatmap(raw)] == [1.0, 0.0, 0.0]

    def test_accepts_yt_dlp_float_boundaries(self):
        raw = [
            {"start_time": 0.0, "end_time": 2.14, "value": 1.0},
            {"start_time": 2.14, "end_time": 4.28, "value": 0.42},
        ]
        assert len(parse_heatmap(raw)) == 2


class TestSelectTopSegments:
    def test_skips_first_60_seconds(self):
        # The intro (first 6 segments of 10 s) is the highest part.
        values = [1.0, 0.99, 0.98, 0.97, 0.96, 0.95, 0.3, 0.8, 0.2, 0.7]
        top = select_top_segments(parse_heatmap(make_heatmap(values)), 2, 60)
        assert [s.start for s in top] == [70.0, 90.0]
        assert all(s.start >= 60 for s in top)

    def test_segment_starting_exactly_at_limit_is_kept(self):
        segments = parse_heatmap(make_heatmap([0.1] * 6 + [0.5]))
        assert [s.start for s in select_top_segments(segments, 5, 60)] == [60.0]

    def test_returns_top_n_sorted_by_time(self):
        values = [0.1] * 6 + [0.9, 0.2, 0.8, 0.3, 0.95, 0.4]
        top = select_top_segments(parse_heatmap(make_heatmap(values)), 3, 60)
        assert [s.value for s in top] == [0.9, 0.8, 0.95]  # time order
        assert [s.start for s in top] == sorted(s.start for s in top)

    def test_ties_prefer_earlier_segments(self):
        values = [0.0] * 6 + [0.5, 0.5, 0.5]
        top = select_top_segments(parse_heatmap(make_heatmap(values)), 2, 60)
        assert [s.start for s in top] == [60.0, 70.0]

    def test_top_n_larger_than_available(self):
        segments = parse_heatmap(make_heatmap([0.2] * 8))
        assert len(select_top_segments(segments, 10, 60)) == 2

    def test_zero_or_negative_top_n(self):
        segments = parse_heatmap(make_heatmap([0.2] * 8))
        assert select_top_segments(segments, 0, 0) == []
        assert select_top_segments(segments, -3, 0) == []


class TestMergeAdjacent:
    def test_merges_touching_segments(self):
        segments = [
            HeatSegment(100, 110, 0.7),
            HeatSegment(110, 120, 0.9),
            HeatSegment(120, 130, 0.8),
            HeatSegment(200, 210, 0.6),
        ]
        moments = merge_adjacent(segments)
        assert len(moments) == 2
        first, second = moments
        assert (first.start, first.end) == (100, 130)
        assert first.score == pytest.approx(0.9)
        assert first.avg_score == pytest.approx(0.8)
        assert first.segment_count == 3
        assert first.peak_time == 110
        assert first.source == SOURCE_HEATMAP
        assert (second.start, second.end, second.segment_count) == (200, 210, 1)

    def test_float_noise_between_segments_is_tolerated(self):
        segments = [HeatSegment(2.14, 4.28, 0.5), HeatSegment(4.2800001, 6.42, 0.6)]
        assert len(merge_adjacent(segments)) == 1

    def test_gap_bigger_than_tolerance_splits(self):
        segments = [HeatSegment(0, 10, 0.5), HeatSegment(12, 20, 0.6)]
        assert len(merge_adjacent(segments, max_gap=0.5)) == 2
        assert len(merge_adjacent(segments, max_gap=3)) == 1

    def test_unsorted_input(self):
        segments = [HeatSegment(20, 30, 0.5), HeatSegment(10, 20, 0.6)]
        moments = merge_adjacent(segments)
        assert len(moments) == 1
        assert (moments[0].start, moments[0].end) == (10, 30)

    def test_empty(self):
        assert merge_adjacent([]) == []


class TestFindHeatmapMoments:
    def test_full_pipeline(self):
        # 20 segments of 10 s. Intro is high; two peaks: 100-130 and 170-180.
        values = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5] + [0.1] * 4
        values += [0.7, 0.9, 0.8] + [0.1] * 4 + [0.85] + [0.1] * 2
        moments = find_heatmap_moments(make_heatmap(values), top_n=4, skip_intro=60)
        assert [(m.start, m.end) for m in moments] == [(100, 130), (170, 180)]
        assert moments[0].score == pytest.approx(0.9)
        assert moments[1].score == pytest.approx(0.85)

    def test_no_heatmap(self):
        assert find_heatmap_moments(None) == []

    def test_typical_100_segment_heatmap(self):
        raw = make_heatmap([0.3] * 100, segment=12.6)
        raw[50]["value"] = 0.9
        moments = find_heatmap_moments(raw)
        assert sum(m.segment_count for m in moments) == 10
        assert any(m.score == pytest.approx(0.9) for m in moments)
        assert all(m.start >= 60 for m in moments)
