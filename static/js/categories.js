/* static/js/categories.js */

// --- DELETE MODAL ---
initDeleteModal(function(deleteModal, openDeleteFor) {
  document.addEventListener('click', function(e) {
    if (e.target && e.target.classList.contains('cat-delete-trigger')) {
      e.preventDefault();
      openDeleteFor(e.target.closest('form'));
    }
  });
});

// --- HIGHLANDER PROTOCOL — only one edit row open at a time ---
function closeAllEditRows() {
  document.querySelectorAll('li').forEach(li => {
    const editMode = li.querySelector('.edit-mode');
    if (editMode && editMode.style.display === 'flex') {
      editMode.style.display = 'none';
      const txMain    = li.querySelector('.tx-main');
      const txActions = li.querySelector('.tx-actions');
      if (txMain)    txMain.style.display    = '';
      if (txActions) txActions.style.display = '';
      const nameInput   = editMode.querySelector('input[type="text"]');
      const hiddenInput = editMode.querySelector('input[name="old_category"]');
      if (nameInput && hiddenInput) nameInput.value = hiddenInput.value;
    }
  });
}

document.querySelectorAll('.toggle-edit-btn').forEach(button => {
  button.addEventListener('click', function(e) {
    e.preventDefault();
    const li        = this.closest('li');
    const editMode  = li.querySelector('.edit-mode');
    const txMain    = li.querySelector('.tx-main');
    const txActions = li.querySelector('.tx-actions');
    const inputField    = editMode.querySelector('input[type="text"]');
    const originalName  = editMode.querySelector('input[name="old_category"]').value;

    if (editMode.style.display === 'flex') {
      editMode.style.display    = 'none';
      if (txMain)    txMain.style.display    = '';
      if (txActions) txActions.style.display = '';
      inputField.value = originalName;
      return;
    }

    closeAllEditRows();
    editMode.style.display = 'flex';
    if (txMain)    txMain.style.display    = 'none';
    if (txActions) txActions.style.display = 'none';
    inputField.focus();
    inputField.select();
  });
});

// --- ADD CATEGORY MODAL ---
const catModal         = document.getElementById('addCategoryModal');
const openCatBtn       = document.getElementById('openCategoryModalBtn');
const closeCatBtn      = document.getElementById('closeCategoryModalBtn');
const mobileCancelCatBtn = document.getElementById('mobileCancelCatBtn');

openCatBtn.addEventListener('click', () => openModal(catModal));
closeCatBtn.addEventListener('click', () => closeModal(catModal));
if (mobileCancelCatBtn) {
  mobileCancelCatBtn.addEventListener('click', () => closeModal(catModal));
}

window.addEventListener('click', (e) => {
  if (e.target === catModal) closeModal(catModal);
});
