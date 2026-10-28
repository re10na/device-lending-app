document.addEventListener('input', (event) => {
  if (!event.target.matches('.employee-search')) return;

  const searchText = event.target.value.trim().toLocaleLowerCase();
  const employeeSelect = event.target.form.querySelector('select[name="shain_code"]');
  for (const option of employeeSelect.options) {
    if (!option.value) continue;
    const matches = option.textContent.toLocaleLowerCase().includes(searchText);
    option.hidden = !matches;
  }
  if (employeeSelect.selectedOptions[0]?.hidden) {
    employeeSelect.value = '';
  }
});
