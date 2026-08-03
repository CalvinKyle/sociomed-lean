# August launch: ranked WhatsApp sourcing and PFI approval

## Summary

- Adds the separate `rfq_requests.pfi_status` lifecycle (`none`, `pending_approval`, `approved`, `held`) in migration `0006`, after the existing line-item/vendor-entity migration chain.
- Ranks owned and partner offers deterministically, caps WhatsApp output at three, adds the fixed overflow handoff, and removes supplier identity and exact stock quantities from buyer messages.
- Resolves quantity-tier prices into single- and multi-line WhatsApp RFQs, then runs a separate field-and-price completeness gate immediately after creation.
- Generates fully priced PFI drafts with the existing generator/numbering, alerts the existing sales/operator number once in real time, and intercepts strict `YES {rfq_id}` / `NO {rfq_id}` commands before buyer conversation routing.
- Adds the proforma estimate/not-final-invoice disclaimer. No PDF is automatically sent.

## Verified prerequisites and branch base

- Work started from the clean `2026_pivot` branch at `081c1f5` and was implemented on `august_launch`.
- The prerequisite `rfq_line_items`, `vendors.is_own_inventory`, `vendors.commission_rate`, `rfq_requests.pfi_reference`, buyer-name capture fix, and `app/services/pfi_generator.py` work was present before implementation.

## Explicit launch assumptions

1. **Ranking threshold:** 10%, implemented once as `OWNED_OFFER_PRICE_ADVANTAGE_THRESHOLD`.
2. **Quantity tiers:** treated as confirmed present. The unit price persisted on each RFQ line is resolved from the tier that contains the requested quantity; a missing matching tier fails closed as unpriced.
3. **Price-completeness gate:** interpreted as mandatory. Any `unit_price=None`/non-positive line prevents PFI generation and the real-time approval alert; the RFQ continues with a price-on-request follow-up.
4. **Legal entity text:** no new legal, tax, or banking string was introduced. The existing template’s `ZELUS LIFE SMC LTD` bank-detail line remains verbatim; the new disclaimer does not name an entity.
5. **Pending-PFI re-alert:** not implemented. The specification says both “no timeout or re-alert at launch” and, later, a working default of a 24-hour digest re-flag. The confirmed architecture and explicit out-of-scope rule were treated as controlling, so pending approvals remain pending indefinitely and the daily digest is unchanged.
6. **PFI artifact handling:** generation validates the PDF and persists the stable PFI reference/status. The existing API-key-gated PDF endpoint regenerates the same internal document for manual founder download/forwarding and refuses unpriced or ungated RFQs. No buyer-facing media delivery was added.
7. **PFI validity:** 30 days, matching the existing generator template.

## Safety properties

- Buyer messages never include supplier name, phone, email, vendor ID, cost, commission, margin, source notes, ownership type, or exact stock quantity.
- Messages shaped like approval commands from non-operator numbers stay in the ordinary buyer flow.
- Ambiguous, unknown, missing, or non-pending operator commands do nothing.
- Approval sends only the fixed buyer courtesy text. The founder still forwards the PDF manually.
- Delivery fees are excluded from automated totals and no price is fabricated.

## Verification

Automated tests cover owned/partner ranking, the 10% boundary, top-three sanitization, Uganda/Kenya currency preservation, fully priced owned and partner RFQs, mixed-price multi-item RFQs, idempotent one-alert generation, operator approval/hold behavior, non-operator command-shaped input, browse-only behavior, quantity-tier line resolution, and the PFI disclaimer.
