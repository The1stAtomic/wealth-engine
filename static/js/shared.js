/* static/js/shared.js
 * Loaded on every page via base.html, before page-specific scripts.
 * Exposes: openModal, closeModal, initDeleteModal
 */

// ── Universal modal helpers ──────────────────────────────────
function openModal(el)  { el.style.display = 'block'; }
function closeModal(el) { el.style.display = 'none';  }

// ── Global Delete Confirmation Modal engine ──────────────────
// Pages call initDeleteModal(registerTrigger) where registerTrigger
// is a function that wires the page-specific open trigger.
//
// registerTrigger receives (deleteModal, openDeleteFor) where:
//   openDeleteFor(form) — stores the form and opens the modal.
//
// Example (net_worth.js / recurring.js):
//   initDeleteModal(function(deleteModal, openDeleteFor) {
//     document.addEventListener('click', function(e) {
//       if (e.target && e.target.classList.contains('delete-btn')) {
//         e.preventDefault();
//         openDeleteFor(e.target.closest('form'));
//       }
//     });
//   });
function initDeleteModal(registerTrigger) {
  const deleteModal     = document.getElementById('deleteModal');
  if (!deleteModal) return;

  const cancelDeleteBtn  = document.getElementById('cancelDeleteBtn');
  const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
  let formToSubmit = null;

  // Let the calling page register its own trigger mechanism
  registerTrigger(deleteModal, function openDeleteFor(form) {
    formToSubmit = form;
    openModal(deleteModal);
  });

  // Shared: cancel clears state and closes
  cancelDeleteBtn.addEventListener('click', () => {
    closeModal(deleteModal);
    formToSubmit = null;
  });

  // Shared: confirm submits the stored form
  confirmDeleteBtn.addEventListener('click', () => {
    if (formToSubmit) formToSubmit.submit();
  });

  // Shared: backdrop click closes and clears
  window.addEventListener('click', e => {
    if (e.target === deleteModal) {
      closeModal(deleteModal);
      formToSubmit = null;
    }
  });
}
