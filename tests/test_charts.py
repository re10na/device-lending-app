"""ダッシュボードの円グラフの形（charts.donut_layout）。"""
import math

from pytest import approx

from device_lending.charts import (
    BUBBLE_ORBIT, BUBBLE_RADIUS, BUBBLE_STEP, LABEL_MIN_SHARE, RING_RADIUS, SEGMENT_GAP, donut_layout,
)


def counts(loaned=0, installed=0, stored=0):
    return {'total': loaned + installed + stored,
            'loaned': loaned, 'installed': installed, 'stored': stored}


def types(*names):
    return [{'device_type': name, 'short_name': name, 'count': 1, 'slot': 1} for name in names]


def test_segments_follow_shares_and_skip_empty():
    layout = donut_layout(counts(loaned=6, stored=2), {})
    assert [s['key'] for s in layout] == ['loaned', 'stored']
    assert layout[0]['offset'] == 0
    assert layout[0]['length'] == approx(75 - SEGMENT_GAP)
    assert layout[1]['offset'] == approx(75)


def test_single_segment_is_full_circle_without_gap():
    assert donut_layout(counts(stored=3), {})[0]['length'] == approx(100)


def test_one_bubble_per_type_centered_on_segment():
    """丸は種別の数だけ、区分の中央を真ん中にして外側に並ぶ。"""
    layout = donut_layout(counts(loaned=4), {'loaned': types('PC', 'SmartPhone', 'Phone')})
    bubbles = layout[0]['bubbles']
    assert [b['device_type'] for b in bubbles] == ['PC', 'SmartPhone', 'Phone']
    assert [b['index'] for b in bubbles] == [0, 1, 2]
    # 区分は円全体なので中央は 50（6 時の位置）。真ん中の丸はその真下
    assert (bubbles[1]['x'], bubbles[1]['y']) == approx((50, 50 + BUBBLE_ORBIT))
    for bubble in bubbles:
        assert math.dist((bubble['x'], bubble['y']), (50, 50)) == approx(BUBBLE_ORBIT, abs=0.01)


def test_bubbles_do_not_overlap():
    layout = donut_layout(counts(installed=5), {'installed': types('PC', 'SmartPhone', 'MobileWifi', 'Phone', 'VoIP')})
    bubbles = layout[0]['bubbles']
    for left, right in zip(bubbles, bubbles[1:]):
        assert math.dist((left['x'], left['y']), (right['x'], right['y'])) > 2 * BUBBLE_RADIUS
    assert BUBBLE_STEP > 0


def test_bubbles_start_on_the_ring():
    bubble = donut_layout(counts(loaned=1), {'loaned': types('PC')})[0]['bubbles'][0]
    assert math.dist((bubble['start_x'], bubble['start_y']), (50, 50)) == approx(RING_RADIUS, abs=0.01)


def test_labels_only_on_segments_big_enough():
    """輪の中の文字は、収まる大きさの区分にだけ書く（輪の上、区分の中央）。"""
    layout = donut_layout(counts(loaned=19, installed=1), {})
    loaned, installed = layout
    assert installed['label_x'] is None                    # 5% < LABEL_MIN_SHARE
    assert math.dist((loaned['label_x'], loaned['label_y']), (50, 50)) == approx(RING_RADIUS, abs=0.01)
    assert LABEL_MIN_SHARE > 5


def test_empty():
    assert donut_layout(counts(), {}) == []
