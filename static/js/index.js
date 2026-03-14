/* static/js/index.js
 * Depends on:
 *   - shared.js    → openModal, closeModal, initDeleteModal
 *   - Chart.js CDN → loaded via {% block extra_head %} in index.html
 *   - Jinja globals injected by index.html inline <script>:
 *       totalDynamicIncome, originalPercentage, originalAmountText,
 *       categoryData, investmentData, trendData, incCategoryData, incTrendData
 */

// --- HUD SHAPE-SHIFTER & LIVE PREVIEW ENGINE ---
const editSavingsBtn      = document.getElementById('editSavingsBtn');
const savingsDisplayValue = document.getElementById('savingsDisplayValue');
const savingsEditWrapper  = document.getElementById('savingsEditWrapper');
const savingsPercentInput = document.getElementById('savingsPercentInput');

editSavingsBtn.addEventListener('click', (e) => {
  e.preventDefault();

  if (!savingsEditWrapper.classList.contains('is-open')) {
    savingsEditWrapper.classList.add('is-open');
    editSavingsBtn.innerText = '[CANCEL]';
  } else {
    savingsEditWrapper.classList.remove('is-open');
    editSavingsBtn.innerText = '[EDIT]';
    savingsPercentInput.value = originalPercentage;
    savingsDisplayValue.innerText = originalAmountText;
    savingsDisplayValue.style.color = '#e0e0e0';
  }
});

// --- MULTI-CURRENCY HOLOGRAPHIC ENGINE ---
const currencyToggleBtn = document.getElementById('currencyToggleBtn');
let isUSD = true;
const KHR_RATE = 4000;

function fmtUSD(val) {
  const sign = val < 0 ? '-' : '';
  return sign + '$' + Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

currencyToggleBtn.addEventListener('click', () => {
  isUSD = !isUSD;

  // Flip the button text and CSS state
  currencyToggleBtn.innerText = isUSD ? '// USD → KHR' : '// KHR → USD';
  currencyToggleBtn.classList.toggle('khr-mode', !isUSD);

  // Sweep the DOM and update every tagged money element
  document.querySelectorAll('.money').forEach(el => {
    let baseUsd = parseFloat(el.getAttribute('data-usd'));
    if (isNaN(baseUsd)) return;

    if (isUSD) {
      el.innerText = fmtUSD(baseUsd);
    } else {
      let khrValue = Math.round(baseUsd * KHR_RATE);
      el.innerText = khrValue.toLocaleString() + ' ៛';
    }
  });

  // Update envelope labels (spent / budget)
  document.querySelectorAll('.envelope-label').forEach(el => {
    let spent  = parseFloat(el.getAttribute('data-usd-spent'));
    let budget = parseFloat(el.getAttribute('data-usd-budget'));
    if (isNaN(spent) || isNaN(budget)) return;
    if (isUSD) {
      el.innerText = fmtUSD(spent) + ' / ' + fmtUSD(budget);
    } else {
      el.innerText = Math.round(spent * KHR_RATE).toLocaleString() + ' / ' + Math.round(budget * KHR_RATE).toLocaleString() + ' ៛';
    }
  });

  // Fire the master chart redraw exactly ONCE after the loop is done
  redrawMasterCharts();
});

// --- CHART MODE STATE ENGINE ---
let chartMode = 'expense';
const chartModeToggleBtn = document.getElementById('chartModeToggleBtn');

if (chartModeToggleBtn) {
  chartModeToggleBtn.addEventListener('click', () => {
    // 1. Flip the state
    chartMode = chartMode === 'expense' ? 'income' : 'expense';

    // 2. Flip the aesthetics using strict CSS classes
    if (chartMode === 'income') {
      chartModeToggleBtn.innerText = '[ MODE: CASH FLOW ]';
      chartModeToggleBtn.classList.remove('mode-expense');
      chartModeToggleBtn.classList.add('mode-income');
    } else {
      chartModeToggleBtn.innerText = '[ MODE: BURN RATE ]';
      chartModeToggleBtn.classList.remove('mode-income');
      chartModeToggleBtn.classList.add('mode-expense');
    }

    // 3. Command the charts to redraw based on the new state
    redrawMasterCharts();
  });
}

// --- HOLOGRAPHIC CHART REDRAW PROTOCOL ---
function redrawMasterCharts() {
  // 1. Determine active payload based on state
  const activeCatData   = chartMode === 'expense' ? categoryData   : incCategoryData;
  const activeTrendData = chartMode === 'expense' ? trendData       : incTrendData;

  // 2. Set dynamic neon colors based on state
  const trendColor = chartMode === 'expense' ? '#00ccff'               : '#00ff66';
  const trendBg    = chartMode === 'expense' ? 'rgba(0, 204, 255, 0.2)' : 'rgba(0, 255, 102, 0.2)';

  // 3. Update Category Doughnut
  catChart.data.labels = Object.keys(activeCatData);
  catChart.data.datasets[0].data = Object.values(activeCatData).map(v => isUSD ? v : Math.round(v * KHR_RATE));
  catChart.options.plugins.title.text = chartMode === 'expense' ? 'EXPENSES BY CATEGORY' : 'INCOME STREAMS';
  catChart.update();

  // 4. Update Investment Bar (remains an expense metric; update currency only)
  invChart.data.datasets[0].data = Object.values(investmentData).map(v => isUSD ? v : Math.round(v * KHR_RATE));
  invChart.data.datasets[0].label = isUSD ? 'Total USD' : 'Total KHR';
  invChart.update();

  // 5. Update Trend Line Chart
  trnChart.data.labels = Object.keys(activeTrendData);
  trnChart.data.datasets[0].data = Object.values(activeTrendData).map(v => isUSD ? v : Math.round(v * KHR_RATE));
  trnChart.data.datasets[0].borderColor = trendColor;
  trnChart.data.datasets[0].backgroundColor = trendBg;
  trnChart.options.plugins.title.text = chartMode === 'expense' ? 'BURN RATE OVER TIME' : 'CASH FLOW OVER TIME';
  trnChart.update();
}

// --- SAVINGS LIVE PREVIEW ---
savingsPercentInput.addEventListener('input', (e) => {
  let currentPercent = parseFloat(e.target.value) || 0;

  if (currentPercent === originalPercentage) {
    savingsDisplayValue.style.color = '#e0e0e0';
    let baseUsd = parseFloat(savingsDisplayValue.getAttribute('data-usd'));
    savingsDisplayValue.innerText = isUSD ? fmtUSD(baseUsd) : (Math.round(baseUsd * KHR_RATE)).toLocaleString() + ' ៛';
  } else {
    let newDollarAmount = (currentPercent / 100) * totalDynamicIncome;
    savingsDisplayValue.style.color = '#ffcc00';
    savingsDisplayValue.innerText = isUSD ? '$' + newDollarAmount.toFixed(2) : (Math.round(newDollarAmount * KHR_RATE)).toLocaleString() + ' ៛';
  }
});

// --- TRANSACTION LOCKOUT PROTOCOL (Anti-Double Submit) ---
const addExpenseForm   = document.querySelector('#addExpenseModal form');
const submitExpenseBtn = document.getElementById('submitBtn');

if (addExpenseForm && submitExpenseBtn) {
  addExpenseForm.addEventListener('submit', () => {
    submitExpenseBtn.disabled = true;
    submitExpenseBtn.style.backgroundColor = '#444';
    submitExpenseBtn.style.color = '#888';
    submitExpenseBtn.style.borderColor = '#444';
    submitExpenseBtn.style.cursor = 'not-allowed';
    submitExpenseBtn.textContent = '[ SAVING ]';
  });
}

// --- ADD EXPENSE MODAL ---
const modal         = document.getElementById('addExpenseModal');
const openModalBtn  = document.getElementById('openModalBtn');
const closeModalBtn = document.getElementById('closeModalBtn');
const mobileCancelBtn = document.getElementById('mobileCancelBtn');

openModalBtn.addEventListener('click', () => {
  openModal(modal);
  document.getElementById('expenseDate').valueAsDate = new Date();
  document.getElementById('addFileName').textContent = 'No file chosen';
  document.querySelector('label[for="addReceiptFile"]').classList.remove('file-selected');
});

closeModalBtn.addEventListener('click', () => closeModal(modal));
if (mobileCancelBtn) {
  mobileCancelBtn.addEventListener('click', () => closeModal(modal));
}

// --- DELETE MODAL (trigger registered; confirm/cancel/backdrop handled by shared.js) ---
initDeleteModal(function(deleteModal, openDeleteFor) {
  document.querySelectorAll('.delete-form').forEach(form => {
    form.addEventListener('submit', e => {
      e.preventDefault();
      openDeleteFor(form);
    });
  });
});

// --- CATEGORY DROPDOWN LOGIC ---
const typeRadio             = document.querySelectorAll('input[name="entry_type"]');
const itemNameInput         = document.getElementById('itemNameInput');
const investmentWrapper     = document.getElementById('investmentWrapper');
const submitBtn             = document.getElementById('submitBtn');
const expenseCategorySelect = document.getElementById('expenseCategorySelect');
const incomeCategorySelect  = document.getElementById('incomeCategorySelect');
const newCategoryInput      = document.getElementById('new_category_input');

typeRadio.forEach(radio => {
  radio.addEventListener('change', (e) => {
    const isInvestmentCheckbox = document.getElementById('is_investment');

    if (e.target.value === 'income') {
      itemNameInput.placeholder = 'Income Name';
      // FIX 1: Hide AND uncheck the investment box to prevent phantom data
      investmentWrapper.style.display = 'none';
      isInvestmentCheckbox.checked = false;
      submitBtn.textContent = 'ADD INCOME';
      submitBtn.classList.add('income-submit');
      // Swap active dropdowns
      expenseCategorySelect.style.display = 'none';
      expenseCategorySelect.disabled = true;
      incomeCategorySelect.style.display = 'block';
      incomeCategorySelect.disabled = false;
      // FIX 2: Re-evaluate the "Add New" input based on the newly active dropdown
      handleCategoryChange(incomeCategorySelect, newCategoryInput);
    } else {
      itemNameInput.placeholder = 'Expense Name';
      investmentWrapper.style.display = '';
      submitBtn.textContent = 'ADD EXPENSE';
      submitBtn.classList.remove('income-submit');
      expenseCategorySelect.style.display = 'block';
      expenseCategorySelect.disabled = false;
      incomeCategorySelect.style.display = 'none';
      incomeCategorySelect.disabled = true;
      handleCategoryChange(expenseCategorySelect, newCategoryInput);
    }
  });
});

// Handle category selection changes — accepts the select and its associated new-category input
function handleCategoryChange(selectElement, newCatInput) {
  const show = selectElement.value === 'add_new';
  newCatInput.style.display = show ? 'block' : 'none';
  newCatInput.required = show;
  if (!show) newCatInput.value = '';
  if (show) newCatInput.focus();
}

expenseCategorySelect.addEventListener('change', function() { handleCategoryChange(this, newCategoryInput); });
incomeCategorySelect.addEventListener('change',  function() { handleCategoryChange(this, newCategoryInput); });

// --- THE INJECTION ENGINE: DYNAMIC EDIT MODAL ---
const editModal                = document.getElementById('editModal');
const closeEditModalBtn        = document.getElementById('closeEditModalBtn');
const editCancelBtn            = document.getElementById('editCancelBtn');
const editForm                 = document.getElementById('editForm');
const editIdDisplay            = document.getElementById('editIdDisplay');
const editItemName             = document.getElementById('editItemName');
const editCost                 = document.getElementById('editCost');
const editExpenseDate          = document.getElementById('editExpenseDate');
const editExpenseType          = document.getElementById('editExpenseType');
const editIncomeType           = document.getElementById('editIncomeType');
const editExpenseCategorySelect = document.getElementById('editExpenseCategorySelect');
const editIncomeCategorySelect  = document.getElementById('editIncomeCategorySelect');
const editInvestmentWrapper    = document.getElementById('editInvestmentWrapper');
const editIsInvestment         = document.getElementById('edit_is_investment');
const editNewCategoryInput     = document.getElementById('edit_new_category_input');
const editNote                 = document.getElementById('editNote');
const editReceiptBlock         = document.getElementById('editReceiptBlock');
const editReceiptLink          = document.getElementById('editReceiptLink');
const removeReceiptChk         = document.getElementById('removeReceiptChk');
const editTypeIndicator        = document.getElementById('editTypeIndicator');
const editSubmitBtn            = document.getElementById('editSubmitBtn');

// Attach listeners to every smart [EDIT] button
document.querySelectorAll('.trigger-edit-modal').forEach(button => {
  button.addEventListener('click', function() {
    // 1. Extract the payload from the button's data attributes
    const id         = this.dataset.id;
    const name       = this.dataset.name;
    const amount     = this.dataset.amount;
    const date       = this.dataset.date;
    const type       = this.dataset.type;
    const category   = this.dataset.category;
    const isInvest   = this.dataset.invest === 'true';
    const note       = this.dataset.note || '';
    const hasReceipt = this.dataset.hasReceipt === 'true';

    // 2. Inject the URL into the form action and display a truncated "Short Hash" ID
    editForm.action = `/edit/${id}`;
    editIdDisplay.innerText = String(id).substring(0, 8).toUpperCase();
    editIdDisplay.title = id;

    // 3. Inject text and numbers
    editItemName.value   = name;
    editCost.value       = parseFloat(amount).toFixed(2);
    editExpenseDate.value = date;

    // 4. Synchronize Dropdowns & Radio Buttons
    if (type === 'income') {
      editIncomeType.checked = true;
      editInvestmentWrapper.style.display = 'none';
      editIsInvestment.checked = false;
      editExpenseCategorySelect.style.display = 'none';
      editExpenseCategorySelect.disabled = true;
      editIncomeCategorySelect.style.display = 'block';
      editIncomeCategorySelect.disabled = false;
      editIncomeCategorySelect.value = category;
      if (editIncomeCategorySelect._refreshCustom) editIncomeCategorySelect._refreshCustom();
    } else {
      editExpenseType.checked = true;
      editInvestmentWrapper.style.display = '';
      editIsInvestment.checked = isInvest;
      editIncomeCategorySelect.style.display = 'none';
      editIncomeCategorySelect.disabled = true;
      editExpenseCategorySelect.style.display = 'block';
      editExpenseCategorySelect.disabled = false;
      editExpenseCategorySelect.value = category;
      if (editExpenseCategorySelect._refreshCustom) editExpenseCategorySelect._refreshCustom();
    }

    // Hide "new category" input by default on open
    editNewCategoryInput.style.display = 'none';
    editNewCategoryInput.required = false;

    // 5. Populate note, receipt, and type indicator
    editNote.value = note;
    if (hasReceipt) {
      editReceiptBlock.style.display = 'flex';
      editReceiptLink.href = `/receipt/${id}`;
    } else {
      editReceiptBlock.style.display = 'none';
    }
    removeReceiptChk.checked = false;
    editTypeIndicator.textContent = type === 'income' ? '[INCOME]' : '[EXPENSE]';
    editTypeIndicator.style.color = type === 'income' ? '#00ff66' : '#ff003c';
    editSubmitBtn.classList.toggle('income-submit', type === 'income');

    // Reset file input display
    document.getElementById('editFileName').textContent = 'No file chosen';
    document.querySelector('label[for="editReceiptFile"]').classList.remove('file-selected');

    // 6. Fire the modal
    openModal(editModal);
  });
});

// Close Edit Modal
const closeEdit = () => closeModal(editModal);
closeEditModalBtn.addEventListener('click', closeEdit);
if (editCancelBtn) editCancelBtn.addEventListener('click', closeEdit);

// Sync Radio Button toggles inside the Edit Modal
document.querySelectorAll('input[name="entry_type"]').forEach(radio => {
  radio.addEventListener('change', (e) => {
    // Only run this if we are interacting with the Edit Modal's radios
    if (e.target.id !== 'editExpenseType' && e.target.id !== 'editIncomeType') return;

    if (e.target.value === 'income') {
      editInvestmentWrapper.style.display = 'none';
      editIsInvestment.checked = false;
      editExpenseCategorySelect.style.display = 'none';
      editExpenseCategorySelect.disabled = true;
      editIncomeCategorySelect.style.display = 'block';
      editIncomeCategorySelect.disabled = false;
      editSubmitBtn.classList.add('income-submit');
    } else {
      editInvestmentWrapper.style.display = '';
      editIncomeCategorySelect.style.display = 'none';
      editIncomeCategorySelect.disabled = true;
      editExpenseCategorySelect.style.display = 'block';
      editExpenseCategorySelect.disabled = false;
      editSubmitBtn.classList.remove('income-submit');
    }
  });
});

editExpenseCategorySelect.addEventListener('change', function() { handleCategoryChange(this, editNewCategoryInput); });
editIncomeCategorySelect.addEventListener('change',  function() { handleCategoryChange(this, editNewCategoryInput); });

// --- FILE INPUT DISPLAY ENGINE ---
function wireFileInput(inputId, labelSelector, displayId) {
  const input   = document.getElementById(inputId);
  const label   = document.querySelector(labelSelector);
  const display = document.getElementById(displayId);
  if (!input || !display) return;
  input.addEventListener('change', () => {
    if (input.files && input.files.length > 0) {
      display.textContent = input.files[0].name;
      if (label) label.classList.add('file-selected');
    } else {
      display.textContent = 'No file chosen';
      if (label) label.classList.remove('file-selected');
    }
  });
}
wireFileInput('addReceiptFile', 'label[for="addReceiptFile"]', 'addFileName');
wireFileInput('editReceiptFile', 'label[for="editReceiptFile"]', 'editFileName');

// --- CHART INITIALIZATION ---
Chart.defaults.color = '#888';
Chart.defaults.font.family = '"Courier New", Courier, monospace';
Chart.defaults.plugins.tooltip.backgroundColor = '#0d0d0d';
Chart.defaults.plugins.tooltip.borderColor = '#333';
Chart.defaults.plugins.tooltip.borderWidth = 1;
Chart.defaults.plugins.tooltip.titleColor = '#e0e0e0';
Chart.defaults.plugins.tooltip.bodyColor = '#888';

// Category Distribution Chart
const ctxCategory = document.getElementById('categoryChart').getContext('2d');
let catChart = new Chart(ctxCategory, {
  type: 'doughnut',
  data: {
    labels: Object.keys(categoryData),
    datasets: [{
      data: Object.values(categoryData),
      backgroundColor: ['#ff003c', '#00ff66', '#00ccff', '#ffcc00', '#e0e0e0', '#555'],
      borderColor: '#0a0a0a',
      borderWidth: 3
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: true,
    aspectRatio: 1.6,
    plugins: {
      title: { display: true, text: 'EXPENSES BY CATEGORY' },
      legend: {
        display: true,
        position: 'right',
        labels: {
          color: '#888',
          font: { family: '"Courier New", Courier, monospace', size: 10 },
          boxWidth: 10,
          padding: 8
        }
      }
    }
  }
});

// Investment vs Sunk Costs Chart
const ctxInvestment = document.getElementById('investmentChart').getContext('2d');
let invChart = new Chart(ctxInvestment, {
  type: 'bar',
  data: {
    labels: Object.keys(investmentData),
    datasets: [{
      label: 'Total USD',
      data: Object.values(investmentData),
      backgroundColor: ['rgba(0,204,255,0.25)', 'rgba(255,0,60,0.25)'],
      borderColor: ['#00ccff', '#ff003c'],
      borderWidth: 1
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      title: { display: true, text: 'INVESTMENTS VS SUNK COSTS' },
      legend: { display: false }
    },
    scales: {
      y: { beginAtZero: true, grid: { color: '#1a1a1a' }, ticks: { color: '#555' } },
      x: { grid: { display: false }, ticks: { color: '#555' } }
    }
  }
});

// Expense Trend Line Chart
const ctxTrend = document.getElementById('trendChart').getContext('2d');
let trnChart = new Chart(ctxTrend, {
  type: 'line',
  data: {
    labels: Object.keys(trendData),
    datasets: [{
      label: 'Total Spent ($)',
      data: Object.values(trendData),
      borderColor: '#00ccff',
      backgroundColor: 'rgba(0, 204, 255, 0.2)',
      borderWidth: 2,
      pointBackgroundColor: '#ffcc00',
      pointBorderColor: '#111',
      pointRadius: 4,
      fill: true,
      tension: 0.1
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      title: { display: true, text: 'EXPENSE TRENDS OVER TIME' },
      legend: { display: false }
    },
    scales: {
      y: { beginAtZero: true, grid: { color: '#1a1a1a' }, ticks: { color: '#555' } },
      x: { grid: { color: '#1a1a1a' }, ticks: { color: '#555' } }
    }
  }
});

// --- LOGOUT MODAL ENGINE ---
const logoutBtn       = document.getElementById('logoutBtn');
const logoutModal     = document.getElementById('logoutModal');
const cancelLogoutBtn = document.getElementById('cancelLogoutBtn');
const confirmLogoutBtn = document.getElementById('confirmLogoutBtn');

// 1. Intercept the click on the logout button
if (logoutBtn) {
  logoutBtn.addEventListener('click', (e) => {
    e.preventDefault();
    openModal(logoutModal);
  });
}

// 2. Cancel button closes the modal
if (cancelLogoutBtn) {
  cancelLogoutBtn.addEventListener('click', () => closeModal(logoutModal));
}

// 3. Confirm button submits the POST form (CSRF-protected)
if (confirmLogoutBtn) {
  confirmLogoutBtn.addEventListener('click', () => {
    document.getElementById('logoutForm').submit();
  });
}

// --- BACKDROP CLICK HANDLER ---
// deleteModal backdrop is handled by shared.js — only handle the remaining modals here
window.addEventListener('click', (event) => {
  [modal, editModal, logoutModal].forEach(m => {
    if (event.target === m) closeModal(m);
  });
});

// --- ADVANCED FILTERS TOGGLE ENGINE ---
const toggleFiltersBtn    = document.getElementById('toggleFiltersBtn');
const filterDrawerWrapper = document.getElementById('filterDrawerWrapper');

// On page load, if Jinja determined the panel should be open, update the button state
if (filterDrawerWrapper && filterDrawerWrapper.classList.contains('is-open')) {
  toggleFiltersBtn.innerText = '[-] FILTERS';
  toggleFiltersBtn.style.backgroundColor = 'rgba(0, 204, 255, 0.1)';
}

if (toggleFiltersBtn && filterDrawerWrapper) {
  toggleFiltersBtn.addEventListener('click', () => {
    const isOpen = filterDrawerWrapper.classList.toggle('is-open');
    if (isOpen) {
      toggleFiltersBtn.innerText = '[-] FILTERS';
      toggleFiltersBtn.style.backgroundColor = 'rgba(0, 204, 255, 0.1)';
    } else {
      toggleFiltersBtn.innerText = '[+] FILTERS';
      toggleFiltersBtn.style.backgroundColor = '#111';
    }
  });
}

// --- ENVELOPE COLLAPSE TOGGLE ---
const envelopeToggle  = document.getElementById('envelopeToggle');
const envelopeSection = envelopeToggle?.closest('.envelope-section');

if (envelopeToggle) {
  envelopeToggle.addEventListener('click', (e) => {
    e.preventDefault();
    envelopeSection.classList.toggle('collapsed');
    envelopeToggle.textContent = envelopeSection.classList.contains('collapsed') ? '[UNCOLLAPSE]' : '[COLLAPSE]';
  });
}
