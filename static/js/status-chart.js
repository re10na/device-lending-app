// ダッシュボードの円グラフ: 区分を押すと、その外側に種別の数だけ丸が飛び出し、
// 中央の数字とリンク先もその区分のものに切り替わる。丸を押すと絞り込んだ機器一覧へ移動する。
// 同じ区分をもう一度押す・円の外を押す・Esc で閉じる
const statusChart = document.querySelector('.placement-chart');

if (statusChart) {
  const centerLink = statusChart.querySelector('.donut-center');
  const centerLabel = statusChart.querySelector('.donut-center-label');
  const centerValue = statusChart.querySelector('.donut-center strong');
  const segments = [...statusChart.querySelectorAll('.segment-link')];
  // 今選んでいる区分（null なら何も選んでいない）
  let current = null;

  const render = (placement) => {
    const segment = segments.find((element) => element.dataset.placement === placement) || null;
    current = segment ? placement : null;
    statusChart.classList.toggle('is-focused', Boolean(current));
    for (const element of statusChart.querySelectorAll('[data-placement]')) {
      element.classList.toggle('is-active', element.dataset.placement === current);
    }
    for (const element of segments) {
      element.setAttribute('aria-expanded', String(element === segment));
    }
    // 出ている丸だけ Tab で移れるようにする
    for (const link of statusChart.querySelectorAll('.bubble-link')) {
      link.tabIndex = link.closest('.donut-bubbles').dataset.placement === current ? 0 : -1;
    }
    centerLabel.textContent = segment ? segment.dataset.label : centerLabel.dataset.default;
    centerValue.textContent = segment ? segment.dataset.value : centerValue.dataset.default;
    centerLink.href = segment ? segment.dataset.href : centerLink.dataset.defaultHref;
  };

  for (const segment of segments) {
    const toggle = () => render(current === segment.dataset.placement ? null : segment.dataset.placement);
    segment.addEventListener('click', toggle);
    segment.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggle();
      }
    });
  }

  // 円の外（四隅のタイルを含む）を押したら閉じる。区分と丸を押したときは閉じない
  document.addEventListener('pointerdown', (event) => {
    if (current && !event.target.closest('.segment-link, .bubble-link, .donut-center')) render(null);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !event.defaultPrevented && current) render(null);
  });

  render(null);
}
