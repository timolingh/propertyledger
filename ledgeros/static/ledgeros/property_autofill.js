(() => {
  function initialize() {
    document.querySelectorAll("form").forEach((form) => {
      const property = form.querySelector('select[name="property"]');
      const unit = form.querySelector('select[data-unit-properties]');
      const tenant = form.querySelector('select[data-tenant-units]');
      if (!property || property.disabled || (!unit && !tenant)) return;
      const units = JSON.parse(unit?.dataset.unitProperties || "{}");
      const tenants = JSON.parse(tenant?.dataset.tenantUnits || "{}");
      const notice = document.createElement("p");
      notice.setAttribute("role", "status");
      notice.className = "muted";
      notice.hidden = true;
      (tenant || unit).after(notice);

      function explain(message) {
        notice.textContent = message;
        notice.hidden = !message;
      }

      unit?.addEventListener("change", () => {
        if (units[unit.value]) property.value = units[unit.value];
        explain("");
        if (tenant?.value && Object.keys(tenants[tenant.value] || {}).length && !tenants[tenant.value][unit.value]) {
          tenant.value = "";
          explain("The tenant selection was cleared. Choose a tenant for this unit if needed.");
        }
      });
      tenant?.addEventListener("change", () => {
        if (!tenant.value) {
          explain("");
          return;
        }
        const matches = tenants[tenant.value] || {};
        const unitIds = Object.keys(matches);
        const propertyIds = [...new Set(Object.values(matches))];
        if (unit && !unit.disabled) unit.value = unitIds.length === 1 ? unitIds[0] : "";
        property.value = propertyIds.length === 1 ? propertyIds[0] : "";
        explain(unitIds.length === 0
          ? "No active lease found for this tenant. Select the property and unit manually."
          : unit && unitIds.length > 1
            ? "This tenant has multiple active units. Select the applicable unit."
            : !unit && propertyIds.length > 1
              ? "This tenant has multiple active properties. Select the applicable property."
              : "");
      });
      property.addEventListener("change", () => {
        if (unit && !unit.disabled && units[unit.value] !== property.value) unit.value = "";
        if (tenant?.value && Object.keys(tenants[tenant.value] || {}).length && !Object.values(tenants[tenant.value]).includes(property.value)) {
          tenant.value = "";
        }
        explain("");
      });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
})();
