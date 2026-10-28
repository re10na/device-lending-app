// 機種を選んだら、その種別で使う照合情報の入力欄だけを表示する。
// JS が動かない場合は全項目が表示されたままで、サーバー側で検証する。
(() => {
  const select = document.getElementById('register-model');
  const form = document.getElementById('register-form');
  if (!select || !form) return;

  const fields = form.querySelectorAll('.identifier-field');
  const hint = form.querySelector('[data-identifier-hint]');
  const knownTypes = new Set();
  for (const field of fields) {
    for (const type of (field.dataset.types || '').split(' ')) {
      if (type) knownTypes.add(type);
    }
  }

  const update = () => {
    const option = select.selectedOptions[0];
    const type = option && option.value ? option.dataset.deviceType : null;
    // 未知の種別は全項目を表示する（設定に無い種別でも登録できるように）
    const showAll = type !== null && !knownTypes.has(type);
    for (const field of fields) {
      const types = (field.dataset.types || '').split(' ').filter(Boolean);
      const visible = types.length === 0
        ? type !== null // シリアル番号など、全種別で使える項目
        : showAll || (type !== null && types.includes(type));
      field.hidden = !visible;
      const input = field.querySelector('input, select');
      input.disabled = !visible;
      if (!visible) input.value = '';
    }
    if (hint) hint.hidden = type === null;
  };

  select.addEventListener('change', update);
  // ダイアログを閉じて入力が初期化されたときも、表示を機種の選択に合わせ直す（reset の後に値が戻るので少し待つ）
  form.addEventListener('reset', () => setTimeout(update));
  update();
  form.classList.add('is-ready');
})();
