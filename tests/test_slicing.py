from gravai.slicing.slice import widen_segments


def test_widen_opens_each_window_earlier_and_closes_it_later():
    assert widen_segments([(10.0, 12.0), (20.0, 25.0)], 0.7, 0.5) == [(9.3, 12.5), (19.3, 25.5)]


def test_widen_never_starts_before_zero():
    assert widen_segments([(0.3, 2.0)], 0.7, 0.5) == [(0.0, 2.5)]


def test_widen_merges_windows_that_touch_after_widening():
    # 12.5 (end of the first, widened) reaches 12.3 (start of the second, widened)
    assert widen_segments([(10.0, 12.0), (13.0, 15.0)], 0.7, 0.5) == [(9.3, 15.5)]


def test_widen_with_zero_padding_keeps_the_windows():
    assert widen_segments([(13.0, 15.0), (10.0, 12.0)], 0, 0) == [(10.0, 12.0), (13.0, 15.0)]


def test_widen_with_no_windows():
    assert widen_segments([], 0.7, 0.5) == []
