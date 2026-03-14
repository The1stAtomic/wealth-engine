/* static/js/login.js */

// --- PASSWORD VISIBILITY ENGINE ---
const toggleBtn = document.getElementById('togglePassword');
const passInput = document.getElementById('loginPassword');

toggleBtn.addEventListener('click', () => {
  const isPassword = passInput.getAttribute('type') === 'password';
  passInput.setAttribute('type', isPassword ? 'text' : 'password');
  toggleBtn.textContent = isPassword ? '[HIDE]' : '[SHOW]';
  toggleBtn.style.color = isPassword ? '#00ff66' : '#888';
});

// --- BOOT SEQUENCE ENGINE ---
document.addEventListener('DOMContentLoaded', () => {
  const logs     = document.querySelectorAll('.sys-log');
  const formArea = document.getElementById('loginFormArea');

  logs.forEach((log, index) => {
    setTimeout(() => { log.style.display = 'block'; }, index * 250);
  });

  setTimeout(() => {
    formArea.style.opacity = '1';
  }, logs.length * 250 + 200);
});
