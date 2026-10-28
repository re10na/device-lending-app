"""ログイン画面と管理者ダッシュボードのルート。"""
from datetime import date

import pymysql
from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for

from .. import auth, charts, devices, events, masters, members, sims, user_requests
from ..config import (
    EVENT_PAGE_SIZE, RETIREMENT_NOTICE_DAYS, SEARCH_MAX_LENGTH, WAITING_REQUEST_PREVIEW,
)
from ..db import transaction
from .auth import landing_url

bp = Blueprint('pages', __name__)


@bp.route('/')
def home():
    """模擬ログインの画面。管理者（ID とパスワード）と利用者（社員番号）の入口。
    すでにログインしていれば、その人の画面へそのまま移動する。
    模擬ログインを使わない設定のときは、組み込み先からログインするよう案内だけを出す。"""
    role = auth.current_role()
    if role:
        return redirect(landing_url(role))
    return render_template('home.html', mock_login=auth.mock_login_enabled())


# 入力中の候補に出す件数（人・機器それぞれ）
SUGGESTION_LIMIT = 5


def _search_query():
    query = request.args.get('q', '').strip()
    if len(query) > SEARCH_MAX_LENGTH:
        abort(400)
    return query


def _search(cursor, query, all_devices):
    """人と機器をまとめて探す。(人, 機器) を返す。"""
    people = members.search_people(masters.fetch_employees(cursor), all_devices, query)
    return people, devices.search_devices(all_devices, query)


def _person_url(person):
    return url_for('members.detail', shain_code=person['shain_code'])


def _device_url(device):
    return url_for('devices.detail', device_id=device['id'])


@bp.route('/admin')
def dashboard():
    query = _search_query()

    try:
        with transaction() as cursor:
            all_devices = devices.fetch_devices(cursor)
            recent_events = events.fetch_recent_events(cursor)
            people, results = _search(cursor, query, all_devices) if query else ([], [])
            pending_requests = user_requests.fetch_pending_requests(cursor)
            confirmed_count = len(user_requests.fetch_confirmed_requests(cursor))
            retirements = members.fetch_upcoming_retirements(cursor, RETIREMENT_NOTICE_DAYS)
            # 円グラフの四隅のタイル（機器一覧・SIM・社員・申請）に添える数
            all_sims = sims.fetch_sims(cursor)
            corner_counts = {
                'sims': len(all_sims),
                'free_sims': sum(1 for sim in all_sims if not sim['device_id']),
                'employees': len(masters.fetch_active_employees(cursor)),
            }
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load dashboard')
        return render_template('load_error.html'), 503

    today = date.today()
    for pending in pending_requests:
        pending['waiting_days'] = (today - pending['requested_at'].date()).days

    # 1 件だけ見つかったときは、検索結果を挟まずにその人・機器のページへ飛ぶ
    if len(people) + len(results) == 1:
        return redirect(_person_url(people[0]) if people else _device_url(results[0]))

    counts = devices.count_devices(all_devices)
    breakdown = devices.type_breakdown(all_devices)
    return render_template(
        'dashboard.html',
        counts=counts,
        donut=charts.donut_layout(counts, breakdown),
        # 申請中は古い順（待たせている順）。先頭の数件だけ名前を出す
        waiting_requests=pending_requests[:WAITING_REQUEST_PREVIEW],
        pending_count=len(pending_requests),
        oldest_wait_days=pending_requests[0]['waiting_days'] if pending_requests else None,
        confirmed_count=confirmed_count,
        retirements=retirements,
        retirement_notice_days=RETIREMENT_NOTICE_DAYS,
        corner_counts=corner_counts,
        recent_events=recent_events,
        query=query,
        people=people,
        results=results,
    )


@bp.get('/admin/search')
def search_suggestions():
    """ダッシュボードの検索欄で、入力中に出す候補（JSON）。"""
    query = _search_query()
    if not query:
        return jsonify(people=[], devices=[], more=0)
    try:
        with transaction() as cursor:
            people, results = _search(cursor, query, devices.fetch_devices(cursor))
    except pymysql.MySQLError:
        current_app.logger.exception('Could not search for suggestions')
        return jsonify(error='検索できませんでした。'), 503

    def person_detail(person):
        parts = [person['shain_code']]
        parts.append(f"貸出 {person['loan_count']} 台" if person['loan_count'] else '貸出なし')
        if person['is_retired']:
            parts.append('退職済み')
        return ' · '.join(parts)

    return jsonify(
        people=[
            {'title': p['name'], 'detail': person_detail(p), 'url': _person_url(p)}
            for p in people[:SUGGESTION_LIMIT]
        ],
        devices=[
            {
                'title': d['display_name'],
                'detail': ' · '.join(filter(None, (d['model_label'], d['placement_label']))),
                'url': _device_url(d),
            }
            for d in results[:SUGGESTION_LIMIT]
        ],
        # 候補に出しきれなかった件数（「すべての結果を見る」に添える）
        more=max(0, len(people) - SUGGESTION_LIMIT) + max(0, len(results) - SUGGESTION_LIMIT),
    )


def render_event_history(sims_only=False, **labels):
    """変更履歴を新しい順に EVENT_PAGE_SIZE 件ずつ表示する（機器全体と SIM の履歴ページで共通）。

    labels は events.html の見出しや戻り先（eyebrow, title, description, empty_text と、
    戻るボタンを出すときだけ back_url, back_label）。
    """
    page = request.args.get('page', 1, type=int)
    if page < 1:
        abort(400)
    try:
        with transaction() as cursor:
            # 1 件多く読んで、次のページがあるかを確かめる
            page_events = events.fetch_events(
                cursor, limit=EVENT_PAGE_SIZE + 1, offset=(page - 1) * EVENT_PAGE_SIZE,
                sims_only=sims_only,
            )
    except pymysql.MySQLError:
        current_app.logger.exception('Could not load event history')
        return render_template('load_error.html'), 503

    return render_template(
        'events.html',
        events=page_events[:EVENT_PAGE_SIZE],
        page=page,
        has_next=len(page_events) > EVENT_PAGE_SIZE,
        first_number=(page - 1) * EVENT_PAGE_SIZE + 1,
        **labels,
    )


@bp.route('/admin/events')
def event_history():
    """機器全体の変更履歴。"""
    return render_event_history(
        eyebrow='DEVICE ACTIVITY',
        title='すべての変更履歴',
        description='貸出・故障・紛失・機器・SIM の記録（新しい順）',
        empty_text='機器を登録すると、ここに変更内容が表示されます。',
    )
