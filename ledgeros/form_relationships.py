"""Read-only relationship hints for existing property workflow fields."""

import json

from ledgeros.models import Lease


def configure_property_autofill(form):
    property_field = form.fields["property"]
    if property_field.disabled:
        return
    property_ids = set(property_field.queryset.values_list("pk", flat=True))
    unit_field = form.fields.get("unit")
    unit_ids = None
    if unit_field is not None and not unit_field.disabled:
        units = {
            str(pk): str(property_id)
            for pk, property_id in unit_field.queryset.values_list("pk", "property_id")
            if property_id in property_ids
        }
        unit_ids = set(units)
        unit_field.widget.attrs["data-unit-properties"] = json.dumps(units)
    tenant_field = form.fields.get("tenant")
    if tenant_field is None or tenant_field.disabled:
        return
    relationships = {}
    leases = Lease.objects.filter(
        status=Lease.Status.ACTIVE,
        tenant_id__in=tenant_field.queryset.values("pk"),
        unit__property_id__in=property_ids,
    ).values_list("tenant_id", "unit_id", "unit__property_id")
    for tenant_id, unit_id, property_id in leases:
        if unit_ids is not None and str(unit_id) not in unit_ids:
            continue
        units = relationships.setdefault(str(tenant_id), {})
        units[str(unit_id)] = str(property_id)
    tenant_field.widget.attrs["data-tenant-units"] = json.dumps(relationships)
