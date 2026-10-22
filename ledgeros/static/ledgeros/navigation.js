(() => {
  const root = document.documentElement;
  const sidebar = document.getElementById('app-sidebar');
  const shell = document.getElementById('page-shell');
  const opener = document.getElementById('sidebar-open');
  const closer = document.getElementById('sidebar-close');
  const collapse = document.getElementById('sidebar-collapse');
  const backdrop = document.getElementById('drawer-backdrop');
  if (!sidebar || !shell || !opener || !closer || !collapse || !backdrop) return;
  root.classList.add('js');
  const mobile = window.matchMedia('(max-width: 760px)');
  let open = false;
  const desktopState = (collapsed) => {
    root.classList.toggle('nav-collapsed', collapsed);
    collapse.setAttribute('aria-expanded', String(!collapsed));
    collapse.textContent = collapsed ? 'Expand navigation' : 'Collapse navigation';
  };
  try { desktopState(localStorage.getItem('propertyledger.navCollapsed') === 'true'); } catch (_) { /* Storage can be disabled. */ }
  collapse.addEventListener('click', () => {
    const collapsed = !root.classList.contains('nav-collapsed');
    desktopState(collapsed);
    try { localStorage.setItem('propertyledger.navCollapsed', String(collapsed)); } catch (_) { /* Navigation still works. */ }
  });
  const drawerState = (next, returnFocus = false) => {
    open = mobile.matches && next;
    sidebar.classList.toggle('is-open', open);
    sidebar.inert = mobile.matches && !open;
    shell.inert = open;
    backdrop.hidden = !open;
    document.body.classList.toggle('drawer-open', open);
    opener.setAttribute('aria-expanded', String(open));
    if (open) {
      sidebar.setAttribute('role', 'dialog');
      sidebar.setAttribute('aria-modal', 'true');
      closer.focus();
    } else {
      sidebar.removeAttribute('role');
      sidebar.removeAttribute('aria-modal');
      if (returnFocus && mobile.matches) opener.focus();
    }
  };
  opener.addEventListener('click', () => drawerState(true));
  closer.addEventListener('click', () => drawerState(false, true));
  backdrop.addEventListener('click', () => drawerState(false, true));
  document.addEventListener('keydown', (event) => {
    if (!open) return;
    if (event.key === 'Escape') { event.preventDefault(); drawerState(false, true); }
    if (event.key === 'Tab') {
      const targets = [...sidebar.querySelectorAll('a[href], button')].filter(el => el.getClientRects().length);
      const first = targets[0], last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  mobile.addEventListener('change', () => drawerState(false));
  drawerState(false);
})();
