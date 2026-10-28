// ダッシュボードの検索欄: 入力中に「人」「機器」の候補を出し、選ぶとそのページへ移動する。
// Enter で候補を選んでいなければ、ふつうに送信して検索結果の一覧を出す
const searchForm = document.querySelector('.quick-search-form');
const SUGGEST_DELAY_MS = 200;

if (searchForm) {
  const input = searchForm.querySelector('input[name="q"]');
  const list = document.getElementById('quick-search-suggestions');
  let options = [];
  let activeIndex = -1;
  let timer;
  let currentRequest;

  const close = () => {
    list.hidden = true;
    list.replaceChildren();
    options = [];
    activeIndex = -1;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  };

  const setActive = (index) => {
    options.forEach((option, i) => option.setAttribute('aria-selected', String(i === index)));
    activeIndex = index;
    if (index >= 0) {
      input.setAttribute('aria-activedescendant', options[index].id);
      options[index].scrollIntoView({ block: 'nearest' });
    } else {
      input.removeAttribute('aria-activedescendant');
    }
  };

  const addGroup = (label, items) => {
    if (!items.length) return;
    const heading = document.createElement('li');
    heading.className = 'suggestion-group';
    heading.setAttribute('role', 'presentation');
    heading.textContent = label;
    list.append(heading);
    for (const item of items) {
      const option = document.createElement('li');
      option.id = `quick-search-option-${options.length}`;
      option.className = 'suggestion';
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      option.dataset.url = item.url;
      const title = document.createElement('strong');
      title.textContent = item.title;
      const detail = document.createElement('span');
      detail.textContent = item.detail;
      option.append(title, detail);
      list.append(option);
      options.push(option);
    }
  };

  const render = (data, query) => {
    list.replaceChildren();
    options = [];
    activeIndex = -1;
    addGroup('人', data.people);
    addGroup('機器', data.devices);
    if (!options.length) {
      const empty = document.createElement('li');
      empty.className = 'suggestion-empty';
      empty.setAttribute('role', 'presentation');
      empty.textContent = `「${query}」に当たる人・機器はありません`;
      list.append(empty);
    } else if (data.more) {
      const more = document.createElement('li');
      more.className = 'suggestion-more';
      more.setAttribute('role', 'presentation');
      more.textContent = `ほか ${data.more} 件。Enter ですべての結果を表示`;
      list.append(more);
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  const suggest = async () => {
    const query = input.value.trim();
    currentRequest?.abort();
    if (!query) {
      close();
      return;
    }
    currentRequest = new AbortController();
    try {
      const url = `${searchForm.dataset.suggestUrl}?${new URLSearchParams({ q: query })}`;
      const response = await fetch(url, { signal: currentRequest.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json(), query);
    } catch (error) {
      // 候補が出せなくても、Enter の検索は使えるので閉じるだけにする
      if (error.name !== 'AbortError') close();
    }
  };

  const scheduleSuggest = () => {
    clearTimeout(timer);
    timer = setTimeout(suggest, SUGGEST_DELAY_MS);
  };

  // 日本語の変換中（確定前）は待つ
  input.addEventListener('input', (event) => {
    if (event.isComposing) return;
    scheduleSuggest();
  });
  input.addEventListener('compositionend', scheduleSuggest);
  input.addEventListener('focus', () => {
    if (input.value.trim() && list.hidden) scheduleSuggest();
  });

  input.addEventListener('keydown', (event) => {
    if (event.isComposing) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (list.hidden || !options.length) return;
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      // 端まで行ったら入力欄（どれも選んでいない状態）に戻る
      let next = activeIndex + step;
      if (next >= options.length) next = -1;
      if (next < -1) next = options.length - 1;
      setActive(next);
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      window.location.href = options[activeIndex].dataset.url;
    } else if (event.key === 'Escape' && !list.hidden) {
      event.preventDefault();
      close();
    }
  });

  // mousedown で選ぶ（click だと先に入力欄の blur で候補が閉じてしまう）
  list.addEventListener('mousedown', (event) => {
    const option = event.target.closest('.suggestion');
    if (!option) return;
    event.preventDefault();
    window.location.href = option.dataset.url;
  });

  input.addEventListener('blur', close);
}
