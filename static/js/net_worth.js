/* static/js/net_worth.js */

// --- ADD ITEM MODAL ---
const addModal     = document.getElementById('addModal');
const openAddBtn   = document.getElementById('openAddModal');
const closeAddBtn  = document.getElementById('closeAddModal');
const cancelAddBtn = document.getElementById('cancelAddModal');

openAddBtn.addEventListener('click', () => openModal(addModal));
closeAddBtn.addEventListener('click', () => closeModal(addModal));
if (cancelAddBtn) cancelAddBtn.addEventListener('click', () => closeModal(addModal));

// --- TYPE RADIO TOGGLE (Consolidated) ---
const submitBtn        = document.getElementById('submitBtn');
const assetOptions     = document.getElementById('assetOptions');
const liabilityOptions = document.getElementById('liabilityOptions');
const addCategory      = document.getElementById('addCategory');

document.querySelectorAll('input[name="item_type"]').forEach(radio => {
  radio.addEventListener('change', function(e) {
    const isLiability = e.target.value === 'liability';
    assetOptions.style.display     = isLiability ? 'none' : '';
    liabilityOptions.style.display = isLiability ? '' : 'none';
    const visibleOptions = addCategory.querySelectorAll('optgroup:not([style*="display: none"]) option');
    if (visibleOptions.length) {
      addCategory.value = visibleOptions[0].value;
    }
    if (isLiability) {
      submitBtn.classList.remove('income-submit');
    } else {
      submitBtn.classList.add('income-submit');
    }
  });
});

window.addEventListener('click', e => {
  if (e.target === addModal) closeModal(addModal);
});

// --- DELETE MODAL ---
initDeleteModal(function(deleteModal, openDeleteFor) {
  document.addEventListener('click', function(e) {
    if (e.target && e.target.classList.contains('delete-btn')) {
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
    }
  });
}

document.querySelectorAll('.toggle-edit-btn').forEach(btn => {
  btn.addEventListener('click', function(e) {
    e.preventDefault();
    const li        = this.closest('li');
    const editMode  = li.querySelector('.edit-mode');
    const txMain    = li.querySelector('.tx-main');
    const txActions = li.querySelector('.tx-actions');

    if (editMode.style.display === 'flex') {
      editMode.style.display = 'none';
      if (txMain)    txMain.style.display    = '';
      if (txActions) txActions.style.display = '';
      return;
    }

    closeAllEditRows();
    editMode.style.display = 'flex';
    if (txMain)    txMain.style.display    = 'none';
    if (txActions) txActions.style.display = 'none';

    const firstInput = editMode.querySelector('input[type="text"]');
    if (firstInput) { firstInput.focus(); firstInput.select(); }
  });
});