const bulkForm = document.getElementById('bulk-review');
if (bulkForm) {
  const eligible = () => [...bulkForm.querySelectorAll('input[name="selected"]:not(:disabled)')];
  const update = () => {
    const count = eligible().filter(input => input.checked).length;
    document.getElementById('selected-post-count').textContent =
      count;
    document.getElementById('bulk-actions').hidden = count === 0;
  };
  bulkForm.addEventListener('change', update);
  document.getElementById('select-page').addEventListener('click', () => {
    eligible().forEach(input => { input.checked = true; });
    update();
  });
  document.getElementById('clear-selection').addEventListener('click', () => {
    eligible().forEach(input => { input.checked = false; });
    update();
  });
  update();
}
