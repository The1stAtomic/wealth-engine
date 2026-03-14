/* static/js/edit.js */

// --- CATEGORY DROPDOWN — show/hide new category input ---
const categoryDropdown = document.querySelector('select[name="category_dropdown"]');
const newCategoryInput = document.getElementById('new_category_input');

categoryDropdown.addEventListener('change', function() {
  if (this.value === 'add_new') {
    newCategoryInput.style.display = 'block';
    newCategoryInput.focus();
    newCategoryInput.required = true;
  } else {
    newCategoryInput.style.display = 'none';
    newCategoryInput.required = false;
    newCategoryInput.value = '';
  }
});
