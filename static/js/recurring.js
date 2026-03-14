/* static/js/recurring.js */

// --- ADD RECURRING MODAL ---
const addRecurringModal     = document.getElementById('addRecurringModal');
const openAddRecurringBtn   = document.getElementById('openAddRecurringBtn');
const closeAddRecurringBtn  = document.getElementById('closeAddRecurringBtn');
const cancelAddRecurringBtn = document.getElementById('cancelAddRecurringBtn');

openAddRecurringBtn.addEventListener('click', () => {
  document.getElementById('recurStartDate').valueAsDate = new Date();
  openModal(addRecurringModal);
});

const closeAddRecurringModal = () => closeModal(addRecurringModal);
closeAddRecurringBtn.addEventListener('click', closeAddRecurringModal);
if (cancelAddRecurringBtn) cancelAddRecurringBtn.addEventListener('click', closeAddRecurringModal);

window.addEventListener('click', (e) => {
  if (e.target === addRecurringModal) closeAddRecurringModal();
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

// --- CATEGORY DROPDOWN + NEW CATEGORY INPUT ---
const recurExpenseSelect     = document.getElementById('recurExpenseCategorySelect');
const recurIncomeSelect      = document.getElementById('recurIncomeCategorySelect');
const recurNewCatInput       = document.getElementById('recurNewCategoryInput');
const recurNewCatLabel       = document.getElementById('recurNewCategoryLabel');
const recurInvestmentWrapper = document.getElementById('recurInvestmentWrapper');

function handleCategoryChange(selectEl, newCatInput) {
  const show = selectEl.value === 'add_new';
  newCatInput.style.display      = show ? 'block' : 'none';
  recurNewCatLabel.style.display = show ? 'block' : 'none';
  newCatInput.required = show;
  if (!show) newCatInput.value = '';
  if (show)  newCatInput.focus();
}

recurExpenseSelect.addEventListener('change', function() { handleCategoryChange(this, recurNewCatInput); });
recurIncomeSelect.addEventListener('change',  function() { handleCategoryChange(this, recurNewCatInput); });

// --- TYPE RADIO TOGGLE ---
const submitBtn = document.getElementById('submitBtn');

document.querySelectorAll('input[name="entry_type"]').forEach(radio => {
  radio.addEventListener('change', (e) => {
    if (e.target.value === 'income') {
      recurExpenseSelect.style.display = 'none';
      recurExpenseSelect.disabled      = true;
      recurIncomeSelect.style.display  = 'block';
      recurIncomeSelect.disabled       = false;
      recurInvestmentWrapper.style.display = 'none';
      document.getElementById('recurIsInvestment').checked = false;
      handleCategoryChange(recurIncomeSelect, recurNewCatInput);
      submitBtn.classList.add('income-submit');
    } else {
      recurIncomeSelect.style.display  = 'none';
      recurIncomeSelect.disabled       = true;
      recurExpenseSelect.style.display = 'block';
      recurExpenseSelect.disabled      = false;
      recurInvestmentWrapper.style.display = '';
      handleCategoryChange(recurExpenseSelect, recurNewCatInput);
      submitBtn.classList.remove('income-submit');
    }
  });
});
