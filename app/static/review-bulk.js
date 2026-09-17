const bulkForm = document.getElementById('bulk-review');
if (bulkForm) {
  bulkForm.addEventListener('change', () => {
    document.getElementById('selected-post-count').textContent =
      bulkForm.querySelectorAll('input[name="selected"]:checked').length;
  });
}
