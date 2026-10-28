"""操作後に元の画面へ戻るためのリダイレクト処理。"""
from flask import redirect, request


def safe_next_url():
    """hidden の next が自サイト内のパスならそれを返す（外部 URL は拒否）。"""
    target = request.form.get('next', '')
    if target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return None


def redirect_back(fallback_url):
    return redirect(safe_next_url() or fallback_url)
