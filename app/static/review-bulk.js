document.querySelectorAll('form[data-bulk-review]').forEach(bulkForm => {
  const eligible = () => [...bulkForm.querySelectorAll('input[name="selected"]:not(:disabled)')];
  const update = () => {
    const count = eligible().filter(input => input.checked).length;
    bulkForm.querySelector('[data-selected-count]').textContent = count;
    bulkForm.querySelector('[data-bulk-actions]').hidden = count === 0;
  };
  bulkForm.addEventListener('change', update);
  bulkForm.querySelector('[data-select-page]').addEventListener('click', () => {
    eligible().forEach(input => { input.checked = true; });
    update();
  });
  bulkForm.querySelector('[data-clear-selection]').addEventListener('click', () => {
    eligible().forEach(input => { input.checked = false; });
    update();
  });
  update();
});
