(() => {
  document.querySelector('[data-payment-errors]')?.focus();
  document.querySelectorAll('[data-dismiss-message]').forEach((button) => {
    button.hidden = false;
    const dismiss = () => {
      window.clearTimeout(timer);
      const restoreFocus = document.activeElement === button;
      const list = button.closest('.messages');
      button.closest('li').remove();
      if (!list.children.length) list.remove();
      if (restoreFocus) document.getElementById('main-content')?.focus();
    };
    const timer = window.setTimeout(dismiss, 10000);
    button.addEventListener('click', dismiss);
  });
})();
