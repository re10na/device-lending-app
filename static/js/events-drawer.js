// ダッシュボードの「最新の変更」を、右から出し入れするパネルにする。
// 開いているかどうかはこのブラウザに覚えておき、次に開いたときも同じ状態にする
const drawer = document.getElementById('events-drawer');
const toggle = document.querySelector('[data-drawer-toggle]');
const STORAGE_KEY = 'events-drawer-open';

function remember(open) {
  try {
    localStorage.setItem(STORAGE_KEY, open ? '1' : '0');
  } catch {
    // 保存できない環境（プライベートブラウズなど）では覚えないだけ
  }
}

function remembered() {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function setOpen(open, { save = true } = {}) {
  drawer.classList.toggle('is-open', open);
  // 閉じているときは Tab で中のリンクに移らないようにする
  drawer.inert = !open;
  toggle.setAttribute('aria-expanded', String(open));
  if (save) remember(open);
}

if (drawer && toggle) {
  toggle.hidden = false;
  if (remembered()) {
    drawer.classList.add('is-instant');
    setOpen(true, { save: false });
    // 開いた状態が描かれてから、次の開け閉めのアニメーションを戻す
    requestAnimationFrame(() => requestAnimationFrame(() => drawer.classList.remove('is-instant')));
  } else {
    setOpen(false, { save: false });
  }

  toggle.addEventListener('click', () => {
    const open = !drawer.classList.contains('is-open');
    setOpen(open);
    if (open) drawer.querySelector('[data-drawer-close]').focus();
  });

  drawer.querySelector('[data-drawer-close]').addEventListener('click', () => {
    setOpen(false);
    toggle.focus();
  });

  // パネルの外を押したら閉じる（押した先のリンクやボタンはそのまま動く）
  document.addEventListener('pointerdown', (event) => {
    if (!drawer.classList.contains('is-open')) return;
    if (drawer.contains(event.target) || toggle.contains(event.target)) return;
    setOpen(false);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !event.defaultPrevented && drawer.classList.contains('is-open')) {
      setOpen(false);
      toggle.focus();
    }
  });
}
