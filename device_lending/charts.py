"""ダッシュボードの円グラフ（ドーナツ型）の形を計算する。画面に出す数字の計算はしない。

輪は円周を 100 とした長さで表す（SVG の pathLength="100" と stroke-dasharray / stroke-dashoffset で描く。
12 時の位置から時計回り）。区分（貸出中・設置中・保管中）を押すと、その区分の外側に
種別の数だけ同じ大きさの丸が飛び出す。丸の位置は SVG の座標（viewBox の中心が 50, 50）で返す。
"""
import math

PLACEMENT_ORDER = ('loaned', 'installed', 'stored')

# 輪の半径（線の中心）と、区分の境目のすき間（円周 100 のうち）。線の太さは CSS（stroke-width: 20）
RING_RADIUS = 30
SEGMENT_GAP = 1.2

# 輪の中に名前と台数を書く区分の大きさの下限（%）。これより小さい区分は文字が収まらないので書かない
LABEL_MIN_SHARE = 9

# 種別の丸の半径、丸の中心を置く半径、隣の丸との間隔（円周 100 のうち）
BUBBLE_RADIUS = 10
BUBBLE_ORBIT = 51
BUBBLE_STEP = 7.5


def _point(radius, position):
    """円周 100 のうち position の位置（12 時が 0、時計回り）の座標。"""
    angle = 2 * math.pi * position / 100 - math.pi / 2
    return round(50 + radius * math.cos(angle), 2), round(50 + radius * math.sin(angle), 2)


def donut_layout(counts, breakdown):
    """区分ごとの弧（offset, length）、輪の中に書く文字の位置（label_x, label_y。書かないなら None）、
    その区分を押したときに出す種別の丸の位置を返す。

    counts は devices.count_devices、breakdown は devices.type_breakdown の結果。
    0 台の区分は含めない。丸は区分の中央を真ん中にして、外側に等間隔で並べる。
    start_x / start_y は飛び出す前の位置（輪の上）。
    """
    total = counts['total']
    shown = [key for key in PLACEMENT_ORDER if counts[key]]
    gap = SEGMENT_GAP if len(shown) > 1 else 0
    segments = []
    offset = 0
    for key in shown:
        share = counts[key] * 100 / total
        length = max(share - gap, 0.01)
        middle = offset + length / 2

        types = breakdown.get(key, [])
        bubbles = []
        for index, row in enumerate(types):
            position = middle + (index - (len(types) - 1) / 2) * BUBBLE_STEP
            x, y = _point(BUBBLE_ORBIT, position)
            start_x, start_y = _point(RING_RADIUS, position)
            bubbles.append(dict(row, x=x, y=y, start_x=start_x, start_y=start_y, index=index))

        label_x, label_y = _point(RING_RADIUS, middle) if share >= LABEL_MIN_SHARE else (None, None)
        segments.append({
            'key': key, 'value': counts[key], 'offset': offset, 'length': length,
            'label_x': label_x, 'label_y': label_y,
            'bubbles': bubbles,
        })
        offset += share
    return segments
