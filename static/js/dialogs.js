// data-open-dialog="<dialog の id>" のボタンでダイアログを開く。
// キャンセル（data-close-dialog）・ダイアログの外側のクリック・Esc キーで閉じる
document.addEventListener('click', (event) => {
  const opener = event.target.closest('[data-open-dialog]');
  if (opener) {
    document.getElementById(opener.dataset.openDialog).showModal();
    return;
  }
  const closer = event.target.closest('[data-close-dialog]');
  if (closer) {
    closer.closest('dialog').close();
    return;
  }
  // 中身は .modal-body が覆っているので、dialog 自体が押されたら外側（背景）のクリック
  if (event.target instanceof HTMLDialogElement) {
    event.target.close();
  }
});

// 閉じたら入力を元に戻す（途中まで入力した値が次に開いたとき残らないように）
document.addEventListener('close', (event) => {
  event.target.querySelector('form')?.reset();
}, true);
