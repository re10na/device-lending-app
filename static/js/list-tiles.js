// 一覧ページの数のタイル・絞り込みの札を、隠してある select を切り替えるボタンとして使う。
// <a data-select="<select の id>" data-value="<値>"> を押すと、その select の値を変えて change を送る
// （各ページの絞り込みの JS が change を受けて一覧を差し替える）。JS が無いときはふつうのリンクとして動く。
// 選んでいるタイル・札には aria-current を付ける。各ページの JS は一覧を差し替えるときに
// window.listTiles.sync() を呼んで、印を select の値に合わせ直す（「解除」で値をまとめて戻したときなど）
(() => {
  const tiles = [...document.querySelectorAll('[data-select][data-value]')];
  if (!tiles.length) return;

  const sync = () => {
    for (const tile of tiles) {
      const select = document.getElementById(tile.dataset.select);
      if (select) tile.toggleAttribute('aria-current', select.value === tile.dataset.value);
    }
  };

  for (const tile of tiles) {
    const select = document.getElementById(tile.dataset.select);
    if (!select) continue;
    tile.addEventListener('click', (event) => {
      event.preventDefault();
      select.value = tile.dataset.value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      sync();
    });
    select.addEventListener('change', sync);
  }

  window.listTiles = { sync };
  sync();
})();
