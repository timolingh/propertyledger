(() => {
  const cents = (value) => {
    const match = /^(\d+)(?:\.(\d{0,2}))?$/.exec(String(value));
    return match ? Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0')) : 0;
  };
  const money = (value) => (value / 100).toFixed(2);
  function initialize() {
    const form = document.querySelector('form[data-receipt-waterfall]');
    if (!form) return;
    const field = (name) => form.elements.namedItem(name);
    const total = field('amount'), invoice = field('invoice_amount'), deposit = field('deposit_amount');
    const other = field('other_amount'), lease = field('deposit_lease'), account = field('other_account_code');
    let preview = JSON.parse(document.getElementById('receipt-waterfall-data').textContent);
    const overrides = new Set();
    for (const input of [invoice, deposit, other]) {
      if (input.disabled || (form.dataset.preserve === 'true' && input.value !== '')) overrides.add(input.name);
      input.addEventListener('input', () => { overrides.add(input.name); recalculate(); });
    }
    function recalculate() {
      let remaining = cents(total.value);
      const selected = preview.leases.find(row => String(row.id) === lease.value);
      const caps = [cents(preview.invoice_due), selected && !selected.blocked ? cents(selected.due) : 0];
      document.getElementById('invoice-due').textContent = money(caps[0]);
      document.getElementById('deposit-due').textContent = selected?.blocked ? 'Needs review — posting unconfirmed' : selected ? money(caps[1]) : 'Choose lease';
      [invoice, deposit, other].forEach((input, index) => {
        if (!overrides.has(input.name)) input.value = money(Math.min(Math.max(0, remaining), caps[index] ?? Math.max(0, remaining)));
        remaining -= cents(input.value);
        document.getElementById(['after-invoices', 'after-deposit', 'after-other'][index]).textContent = money(remaining);
      });
      account.required = cents(other.value) > 0 && !account.disabled;
      const status = document.getElementById('waterfall-status');
      status.textContent = remaining < 0 ? 'Allocations exceed the amount received. Reduce the split.'
        : remaining > 0 ? `${money(remaining)} remains unallocated. Adjust the split before posting.`
          : 'The full amount is allocated. Review all three rows before posting.';
      const post = form.querySelector('button[value="post"]');
      if (post) post.disabled = remaining !== 0 || cents(total.value) === 0;
    }
    function updateLeaseOptions() {
      const current = lease.value;
      if (!lease.disabled) {
        lease.replaceChildren(new Option('Choose deposit lease', ''));
        preview.leases.forEach(row => lease.add(new Option(row.label, row.id)));
        if (preview.leases.some(row => String(row.id) === current)) lease.value = current;
        else if (preview.leases.length === 1) lease.value = String(preview.leases[0].id);
      }
      const list = document.getElementById('waterfall-invoices');
      list.replaceChildren();
      for (const row of preview.invoices) {
        const item = document.createElement('li');
        item.textContent = `${row.label} — ${row.due}`;
        list.append(item);
      }
    }
    let requestNumber = 0;
    async function load() {
      const number = ++requestNumber;
      const params = new URLSearchParams({property: field('property').value, tenant: field('tenant').value});
      if (form.dataset.payment) params.set('payment', form.dataset.payment);
      try {
        const response = await fetch(`${form.dataset.receiptWaterfall}?${params}`, {headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error('Preview unavailable');
        const result = await response.json();
        if (number !== requestNumber) return;
        preview = result;
        updateLeaseOptions(); recalculate();
      } catch {
        if (number === requestNumber) document.getElementById('waterfall-status').textContent = 'Allocation preview unavailable. Reload before posting; saved balances will be checked again.';
      }
    }
    total.addEventListener('input', recalculate);
    lease.addEventListener('change', recalculate);
    field('property').addEventListener('change', load);
    field('tenant').addEventListener('change', load);
    updateLeaseOptions(); recalculate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
})();
