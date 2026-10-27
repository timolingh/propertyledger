(() => {
  function initialize() {
    const vendor = document.getElementById("id_vendor");
    const billDate = document.getElementById("id_bill_date");
    const dueDate = document.getElementById("id_due_date");
    if (!vendor || !billDate || !dueDate || dueDate.disabled) return;
    let automatic = dueDate.dataset.autoDefault === "true";

    function updateDueDate() {
      if (!automatic || !billDate.value) return;
      const date = new Date(`${billDate.value}T00:00:00Z`);
      if (Number.isNaN(date.getTime())) return;
      const days = Number(vendor.selectedOptions[0]?.dataset.paymentDays || 0);
      date.setUTCDate(date.getUTCDate() + days);
      dueDate.value = date.toISOString().slice(0, 10);
    }

    dueDate.addEventListener("input", () => { automatic = !dueDate.value; });
    vendor.addEventListener("change", updateDueDate);
    billDate.addEventListener("change", updateDueDate);
    updateDueDate();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
