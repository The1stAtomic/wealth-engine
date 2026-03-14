/* static/js/trash.js */

// --- Collapsible expiry drawer ---
const configureExpiryBtn = document.getElementById('configureExpiryBtn');
const expiryDrawer       = document.getElementById('expiryDrawer');
configureExpiryBtn.addEventListener('click', () => {
  expiryDrawer.classList.toggle('is-open');
  configureExpiryBtn.textContent = '[CONFIGURE]';
});

// --- Single-item purge modal ---
const purgeModal      = document.getElementById('purgeModal');
const cancelPurgeBtn  = document.getElementById('cancelPurgeBtn');
const confirmPurgeBtn = document.getElementById('confirmPurgeBtn');
let formToSubmit = null;

document.addEventListener('click', function(e) {
  if (e.target && e.target.classList.contains('trash-cmd-purge')) {
    e.preventDefault();
    formToSubmit = e.target.closest('form');
    openModal(purgeModal);
  }
});
cancelPurgeBtn.addEventListener('click',  () => { closeModal(purgeModal); formToSubmit = null; });
confirmPurgeBtn.addEventListener('click', () => { if (formToSubmit) formToSubmit.submit(); });

// --- Bulk select ---
const bulkForm       = document.getElementById('bulkForm');
const bulkAction     = document.getElementById('bulkAction');
const actionBar      = document.getElementById('actionBar');
const selectAllCb    = document.getElementById('selectAll');
const selectionCount = document.getElementById('selectionCount');
const restoreCount   = document.getElementById('restoreCount');
const purgeCount     = document.getElementById('purgeCount');
const bulkRestoreBtn = document.getElementById('bulkRestoreBtn');
const bulkPurgeBtn   = document.getElementById('bulkPurgeBtn');
const purgeAllBtn    = document.getElementById('purgeAllBtn');

function getChecked() {
  return [...document.querySelectorAll('.tx-checkbox:checked')];
}

function updateBar() {
  const checked = getChecked();
  const n = checked.length;
  if (n > 0) {
    actionBar.style.display    = 'flex';
    selectionCount.textContent = n + ' selected';
    restoreCount.textContent   = n;
    purgeCount.textContent     = n;
  } else {
    actionBar.style.display = 'none';
  }
  const all = document.querySelectorAll('.tx-checkbox');
  if (selectAllCb) {
    selectAllCb.indeterminate = n > 0 && n < all.length;
    selectAllCb.checked = all.length > 0 && n === all.length;
  }
}

document.querySelectorAll('.tx-checkbox').forEach(cb => cb.addEventListener('change', updateBar));

if (selectAllCb) {
  selectAllCb.addEventListener('change', () => {
    document.querySelectorAll('.tx-checkbox').forEach(cb => { cb.checked = selectAllCb.checked; });
    updateBar();
  });
}

function submitBulk(action) {
  bulkForm.querySelectorAll('input[name="tx_ids"]').forEach(el => el.remove());
  getChecked().forEach(cb => {
    const inp   = document.createElement('input');
    inp.type  = 'hidden';
    inp.name  = 'tx_ids';
    inp.value = cb.value;
    bulkForm.appendChild(inp);
  });
  bulkAction.value = action;
  bulkForm.submit();
}

// --- Bulk purge / Purge All modal ---
const purgeAllModal      = document.getElementById('purgeAllModal');
const purgeAllModalTitle = document.getElementById('purgeAllModalTitle');
const purgeAllModalBody  = document.getElementById('purgeAllModalBody');
const cancelPurgeAllBtn  = document.getElementById('cancelPurgeAllBtn');
const confirmPurgeAllBtn = document.getElementById('confirmPurgeAllBtn');

function openPurgeAllModal(title, body) {
  purgeAllModalTitle.textContent = title;
  purgeAllModalBody.textContent  = body;
  openModal(purgeAllModal);
}

if (purgeAllBtn) {
  purgeAllBtn.addEventListener('click', () => {
    document.querySelectorAll('.tx-checkbox').forEach(cb => { cb.checked = true; });
    updateBar();
    openPurgeAllModal('Purge All', 'Permanently delete every item in trash? This cannot be undone.');
  });
}

if (bulkPurgeBtn) {
  bulkPurgeBtn.addEventListener('click', () => {
    const n = getChecked().length;
    if (!n) return;
    openPurgeAllModal(
      'Purge Selected',
      'Permanently delete ' + n + ' selected item' + (n === 1 ? '' : 's') + '? This cannot be undone.'
    );
  });
}

cancelPurgeAllBtn.addEventListener('click',  () => closeModal(purgeAllModal));
confirmPurgeAllBtn.addEventListener('click', () => submitBulk('purge'));

// --- Bulk restore modal ---
const bulkRestoreModal      = document.getElementById('bulkRestoreModal');
const bulkRestoreBody       = document.getElementById('bulkRestoreBody');
const cancelBulkRestoreBtn  = document.getElementById('cancelBulkRestoreBtn');
const confirmBulkRestoreBtn = document.getElementById('confirmBulkRestoreBtn');

if (bulkRestoreBtn) {
  bulkRestoreBtn.addEventListener('click', () => {
    const n = getChecked().length;
    if (!n) return;
    bulkRestoreBody.textContent = 'Restore ' + n + ' selected item' + (n === 1 ? '' : 's') + ' back to your records?';
    openModal(bulkRestoreModal);
  });
}

cancelBulkRestoreBtn.addEventListener('click',  () => closeModal(bulkRestoreModal));
confirmBulkRestoreBtn.addEventListener('click', () => submitBulk('restore'));

// --- Backdrop clicks ---
window.addEventListener('click', e => {
  if (e.target === purgeModal)       { closeModal(purgeModal); formToSubmit = null; }
  if (e.target === purgeAllModal)    { closeModal(purgeAllModal); }
  if (e.target === bulkRestoreModal) { closeModal(bulkRestoreModal); }
});
