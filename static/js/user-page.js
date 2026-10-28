// 利用者画面: 社員・種別を選んだ時点で表示する（「表示」「絞り込む」ボタンを押す手間を省く）
document.addEventListener('change', (event) => {
  if (!event.target.matches('select[data-auto-submit]')) return;
  // 社員の選択を空に戻したときは送らない（required で止まるだけなので）
  if (event.target.required && !event.target.value) return;
  event.target.form.requestSubmit();
});

// 表の「不具合を申請」「この機種を申請」: 下の申請フォームで対象を選んだ状態にして、入力欄へ移動する
document.addEventListener('click', (event) => {
  const link = event.target.closest('[data-fill-select]');
  if (!link) return;
  const select = document.getElementById(link.dataset.fillSelect);
  const field = document.getElementById(link.dataset.focus);
  if (!select || !field) return;

  event.preventDefault();
  select.value = link.dataset.value;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  field.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
  field.focus({ preventScroll: true });
});
