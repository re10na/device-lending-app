// 機器一覧の絞り込み: 選んだ・入力した時点で、ページを読み込み直さずに表と件数だけを差し替える
const filterForm = document.querySelector('.inventory-filter');
const placementSelect = document.getElementById('placement-filter');
const flagSelect = document.getElementById('flag-filter');
const typeSelect = document.getElementById('type-filter');
const holderSelect = document.getElementById('holder-filter');
const keywordInput = document.getElementById('keyword-filter');
const clearLink = document.getElementById('clear-filter');
const exportLink = document.getElementById('export-csv');
const KEYWORD_DELAY_MS = 400;

// 「状態」「注意」「種別」の選択に合う人だけを「借りている人」の選択肢に残す
function updateHolderOptions() {
  const placement = placementSelect.value;
  const flag = flagSelect.value;
  const type = typeSelect.value;
  // 借りている人がいるのは貸出中の機器だけ
  const placementMatches = placement === 'all' || placement === 'loaned';
  for (const option of holderSelect.options) {
    if (!option.value) continue;
    const flags = option.dataset.flags.split(' ');
    // 種別名にはスペースが入りうるので | で区切っている
    const types = option.dataset.types.split('|');
    const matches = placementMatches
      && (!flag || flags.includes(flag))
      && (!type || types.includes(type));
    option.hidden = !matches;
    option.disabled = !matches;
  }
  if (holderSelect.selectedOptions[0]?.hidden) {
    holderSelect.value = '';
  }
}

// 今の選択からクエリ文字列を作る（未指定の項目は付けない）
function filterQuery() {
  const params = new URLSearchParams();
  for (const [name, value] of new FormData(filterForm)) {
    const trimmed = value.trim();
    if (trimmed && !(name === 'placement' && trimmed === 'all')) params.set(name, trimmed);
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

let currentRequest;

async function applyFilter() {
  // 状態のタイル・注意の札の「選んでいる」印を、今の select の値に合わせる（list-tiles.js）
  window.listTiles?.sync();
  const query = filterQuery();
  const url = filterForm.action + query;
  // 前の問い合わせがまだ返っていなければ取り消す（古い結果で上書きしないため）
  currentRequest?.abort();
  currentRequest = new AbortController();
  try {
    const response = await fetch(url, { signal: currentRequest.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    for (const id of ['device-results', 'device-count']) {
      document.getElementById(id).replaceWith(page.getElementById(id));
    }
    clearLink.hidden = page.getElementById('clear-filter').hidden;
    history.replaceState(null, '', url);
    // CSV も今の絞り込みで出力されるようにする
    exportLink.href = exportLink.dataset.base + query;
  } catch (error) {
    if (error.name === 'AbortError') return;
    // うまくいかないときは、今までどおりページごと読み込む
    window.location.href = url;
  }
}

if (filterForm) {
  updateHolderOptions();

  // Enter キーで送信されたときも、読み込み直さずに差し替える
  filterForm.addEventListener('submit', (event) => {
    event.preventDefault();
    applyFilter();
  });

  for (const select of [placementSelect, flagSelect, typeSelect]) {
    select.addEventListener('change', () => {
      updateHolderOptions();
      applyFilter();
    });
  }
  holderSelect.addEventListener('change', applyFilter);

  // キーワードは入力が止まってから絞り込む。日本語の変換中（確定前）は待つ
  let keywordTimer;
  const scheduleKeywordFilter = () => {
    clearTimeout(keywordTimer);
    keywordTimer = setTimeout(applyFilter, KEYWORD_DELAY_MS);
  };
  keywordInput.addEventListener('input', (event) => {
    if (event.isComposing) return;
    scheduleKeywordFilter();
  });
  keywordInput.addEventListener('compositionend', scheduleKeywordFilter);

  clearLink.addEventListener('click', (event) => {
    event.preventDefault();
    placementSelect.value = 'all';
    flagSelect.value = '';
    typeSelect.value = '';
    holderSelect.value = '';
    keywordInput.value = '';
    updateHolderOptions();
    applyFilter();
  });
}
