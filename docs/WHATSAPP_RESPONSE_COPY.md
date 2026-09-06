# SocioMED WhatsApp response copy

This is the human-readable review deck for every static automatic response currently loaded from `app/content/conversation_copy.json`. It contains all 79 copy keys. Edit the JSON values—not the keys—in the source file; preserve every `{placeholder}` exactly.

## Delivered-wordmark rule

Every outbound WhatsApp message passes through one sender. If the exact wordmark `SocioMED` is not already present, delivery appends:

```text

— SocioMED
```

Messages already containing `SocioMED` are not given a duplicate footer. This applies to buyer replies, supplier RFQs, sales leads, daily digests, and failure messages. It is a visual provenance cue, not cryptographic proof; provider message IDs and audit records remain the authoritative authenticity check.

## Dynamic assembly rules

Some delivered messages combine the templates below with live catalog values. Category lists insert numbered category or product rows between their header and footer. Search results repeat the title, optional SKU, price summary, availability, and up to three pricing tiers for each supplier option. Related products are appended after the offer list. RFQ confirmations insert the database RFQ ID and either the supplier-notified or manual-routing sentence. All resulting messages then pass through the delivered-wordmark rule above.

## Session, navigation, and input handling

### Main menu — `main_menu`

```text
Welcome to SocioMED!

What medical supply do you need today? You may type a product immediately.

1. Search products
2. Browse categories
3. Request a quotation
4. Talk to sales
0. Main menu

Type END at any time to close this session.
```

### Help — `help`

```text
How SocioMED works:
1. Search a product such as surgical gloves or oxygen mask.
2. View featured offers when you want a quick shortlist.
3. Request a quotation and we shall notify the sales team to follow up.
4. Talk to sales for urgent or complex sourcing needs.
5. Browse by category when you want to scan product families first.

Use 0 at any time to return to the main menu, or END to close the session.
```

### Search prompt — `search_prompt`

```text
What medical supply are you looking for?
```

### Unknown state — `unknown_state`

```text
I did not understand that. Reply 0 for the main menu.
```

### Message too long or unsafe — `message_too_long`

```text
Please send a shorter message using normal text, numbers, and punctuation.
```

### Unsupported media type — `unsupported_message`

```text
I received your {message_type}, but this procurement flow works best with typed text right now.

Please type your reply as text so I can keep helping you. You can also send 0 to return to the main menu.
```

### Session closed — `conversation_closed`

```text
Thank you for contacting SocioMED. This session is now closed. You can message us again at any time to start a new request.
```

### Worker failure — `worker_failure`

```text
Sorry, I could not complete that request right now. Your message has not been ignored. Please try again shortly, or reply 4 from the main menu to contact sales.
```

## Entry, returning buyers, restrictions, and sales

### Short sales prompt — `sales_prompt_short`

```text
Reply with: Name | Organization | What you need. We will connect you directly with a salesperson.
```

### Sales prompt with example — `sales_prompt`

```text
Reply with: Name | Organization | What you need.
Example: Amina | City Care Hospital | Need 500 pairs of gloves urgently
```

### Sales handoff prompt — `sales_handoff_prompt`

```text
Reply with: name | organization | what you need.
We will connect you directly with a salesperson.
```

### Restricted medicine — `restricted_medicine`

```text
SocioMED handles medical supplies and equipment, not medicines. Type the supply item you need, or reply SALES for help.
```

### Returning-buyer greeting — `returning_greeting`

```text
Welcome back, {first_name}.

{menu}
```

### Returning-buyer RFQ prompt — `returning_rfq`

```text
Welcome back, {first_name}. Reply item | quantity to reuse {organization} and {delivery_location}, or use the full format to change them.

{prompt}
```

### Unrecognized entry — `entry_fallback`

```text
Type a medical supply, QUOTE for a formal request, CATEGORIES to browse, or SALES for help. Reply MENU to see all options.
```

### Sales handoff failed — `sales_handoff_error`

```text
We could not hand this off to sales right now. Please try again shortly.
```

### Sales handoff accepted — `sales_handoff_received`

```text
Your request has been shared with our sales team. Lead #{lead_id} is now open and someone will reach out shortly.

If you are finished, reply END to close this session.
```

## Featured offers and category browsing

### No featured offers — `no_featured_offers`

```text
No featured offers are available right now. Reply 1 to search the catalog.
```

### Featured-offer header — `featured_header`

```text
Featured procurement offers:

```

### One featured-offer row — `featured_offer`

```text
{index}. {product_name} - {brand} from {vendor_name}
From {price_text} per {uom} | Stock {stock_qty} | Lead time {lead_time_days} days
```

### Featured-offer footer — `featured_footer`

```text

Reply with the product name you want to search, or reply 3 to request a quotation.
```

### No categories — `no_categories`

```text
No catalog categories are available right now. Reply 1 to search directly or 3 to request a quotation.
```

### Category-list header — `categories_header`

```text
Browse procurement categories:

```

### Category-list footer — `categories_footer`

```text

Reply with the category number or exact category name.
Use 0 at any time to return to the main menu.
```

### Empty selected category — `category_empty`

```text
We do not have products listed in {category_name} yet.
Reply with another category number, or use 0 to return to the main menu.
```

### Category-product header — `category_products_header`

```text
{category_name} products:

```

### More products than the numbered list — `category_products_overflow`

```text
Type the exact product name if you do not see it in the numbered list.
```

### Category-product footer — `category_products_footer`

```text
Reply with the product number you want to price first, or type the exact product name.
Use 0 at any time to return to the main menu.
```

### Invalid category — `category_invalid`

```text
Please reply with one of the category numbers shown, or type the exact category name.
```

### Invalid product inside a category — `category_product_invalid`

```text
Please reply with one of the product numbers shown, or type the exact product name from that category.
```

### Category product has no live offer — `category_no_live_offer`

```text
We found the product, but there is no validated live price for it right now.
Reply with another product number, type another product name, or use 3 from the main menu to request a quotation.
```

## Search, bulk detection, and disambiguation

### Bulk list detected — `bulk_detected`

```text
This looks like a multi-item sourcing list, so we should capture it as one RFQ for manual routing.
```

### Large or complex bulk list — `bulk_complex`

```text
This looks like a larger bulk sourcing list, so a SocioMED agent should triage it as one RFQ.
```

### Invalid product search — `search_invalid`

```text
Please enter a clear product search such as surgical gloves, IV set, or oxygen mask.
```

### No matching product — `search_no_match`

```text
I could not find that exact product.

Reply SEARCH to try another term, or SALES for help.
```

### Product found without live offer from menu search — `search_no_live_offer_menu`

```text
We found the product, but there is no validated live price for it right now. Reply 3 from the main menu and SocioMED can source a quotation.
```

### Product found without live offer after disambiguation — `search_no_live_offer_rfq`

```text
We found the product, but there is no validated live price for it right now.
Reply RFQ to request a manual quotation, or AGENT for a sourcing handoff.
```

### Quantity was detected in the original search — `requested_quantity`

```text
Requested quantity: {quantity} {uom}.

{results}
```

### Ambiguous-match header — `ambiguous_header`

```text
I found multiple possible matches:
```

### Ambiguous large-list next step — `ambiguous_next_large`

```text
Reply with the product number to price one item first.
Reply RFQ if this is a bulk request, or AGENT for a sourcing handoff.
```

### Ambiguous small-list next step — `ambiguous_next_small`

```text
Reply with the product number you want to price first. Reply RFQ for a manual quotation, or AGENT for sales.
```

### Invalid disambiguation reply — `disambiguation_invalid`

```text
Please reply with one of the product numbers shown, RFQ for a manual quotation, or AGENT for sales.
```

## Offers, availability, and related items

### No offer options — `results_empty`

```text
No options available. Type 0 to return to the menu.
```

### Offer-list header — `results_header`

```text
*{product_name} – Available Options*

Reply with the offer number you want to request.


```

### Offer title — `result_title`

```text
*{counter}. {brand}*

```

### Offer SKU line — `result_sku`

```text
SKU: {sku}

```

### Offer unit and price range — `result_summary`

```text
UoM: {uom} | {price_range}

```

### Offer availability line — `result_availability`

```text
Min qty: {min_qty} {uom} | Availability: {availability} | Indicative lead time: {lead_time_days} days

```

### Offer-list footer — `results_footer`

```text
0 → Main menu | END → Close session
```

### Availability label: in stock — `availability_in_stock`

```text
Available
```

### Availability label: sourcing — `availability_sourcing`

```text
Sourcing available
```

### Related-items header — `related_header`

```text
Complete this order with:
```

### One related-item row — `related_offer`

```text
R{index}. {product_name} from {price_text} per {uom}
```

### Related-items footer — `related_footer`

```text
Reply with R1, R2, or R3 to view that related item.
```

### Invalid related-item reply — `related_invalid`

```text
That related item is not available. Reply with an offer number or 0 for menu.
```

### Related item no longer exists — `related_missing`

```text
That related item is no longer available. Reply 0 for the main menu.
```

### Related item has no live offer — `related_no_live_offer`

```text
We do not have a validated live offer for that related item right now.
```

### Non-numeric offer reply — `offer_number_prompt`

```text
Reply with the offer number you want, or 0 for the main menu.
```

### Offer selected — `offer_selected`

```text
You selected the {brand} option.
{sku_line}UoM: {uom}
Minimum order: {min_qty} {uom}
Availability and delivery timing will be confirmed in the quotation.

How many {uom} do you need?
```

### Offer number out of range — `offer_invalid`

```text
That option is not available. Reply with one of the offer numbers shown.
```

## Quantity and estimated price

### Quantity is not a whole number — `quantity_integer`

```text
Please reply with a quantity as a whole number.
```

### Quantity is zero or negative — `quantity_positive`

```text
Please reply with a quantity greater than zero.
```

### Quantity is below minimum — `quantity_below_minimum`

```text
Minimum order for this offer is {minimum_quantity} {uom}.
```

### Estimated-price menu — `price_menu`

```text
Estimated starting price: {price_text} per {uom}.

Reply with:
1. Request quotation
2. Talk to sales
3. Back to search results
0. Main menu

Type END if you are finished.
```

### Returning to offer list — `returning_to_offers`

```text
Returning to the supplier offers.
```

### Invalid estimated-price reply — `price_menu_invalid`

```text
Please reply with 1, 2, 3, or 0.
```

## Quotation capture and confirmation

### Direct RFQ instructions — `direct_rfq_prompt`

```text
Reply with your RFQ in one message: your name, then item(s), quantity, facility, and delivery location.

Single item:
Dr. Ali | surgical gloves | 10 | Mulago Hospital | Kampala

Bulk list:
Dr. Ali | gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala
```

### RFQ contact details prompt — `rfq_contact_prompt`

```text
Reply with your name, facility/client name, and delivery location.
Example: Dr. Ali, Mulago Hospital, Kampala
```

### Guided RFQ submission failure — `rfq_submit_error`

```text
We could not submit your quotation request right now. Please try again shortly.
```

### Supplier successfully notified — `supplier_notified`

```text
The supplier has been notified.
```

### Manual sales routing — `supplier_manual`

```text
Our sales team will route it manually.
```

### Guided RFQ accepted — `rfq_received`

```text
Quotation request received. RFQ #{rfq_id} has been created.
{routing_message}
A follow-up will be shared with you shortly.

If you are finished, reply END to close this session.
```

### Direct RFQ format invalid — `direct_rfq_invalid_format`

```text
Please use one of these formats:

Single item:
Dr. Ali | surgical gloves | 10 | Mulago Hospital | Kampala

Bulk list:
Dr. Ali | gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala
```

### Direct RFQ data invalid — `direct_rfq_invalid_data`

```text
Please send a valid name, quantity, facility/client name, and delivery location.
```

### Direct RFQ submission failure — `direct_rfq_submit_error`

```text
We could not capture your quotation request right now. Please try again.
```

### Bulk RFQ accepted — `bulk_rfq_received`

```text
Your bulk quotation request has been logged as RFQ #{rfq_id}.
A SocioMED agent will triage the list, match suppliers, and follow up with options.

If you are finished, reply END to close this session.
```

### Single direct RFQ accepted — `direct_rfq_received`

```text
Your quotation request has been logged as RFQ #{rfq_id}.
Our team will match it to suppliers and follow up with you.

If you are finished, reply END to close this session.
```

## Order-status follow-up

### Order confirmed — `buyer_status_confirmed`

```text
Good news — your order (RFQ #{rfq_id}) for {product_name} is confirmed. The supplier is preparing it and we'll follow up with delivery details shortly.
```

### Order fulfilled — `buyer_status_fulfilled`

```text
Your order (RFQ #{rfq_id}) for {product_name} has been fulfilled. Thank you for sourcing through SocioMED — reply 1 any time to start your next order, or END to close the session.
```

## Operational messages to suppliers and sales

These messages are generated from database fields rather than the copy JSON, and they receive the same `— SocioMED` footer.

### New supplier or sales RFQ

```text
New procurement RFQ
RFQ ID: {rfq_id}
Buyer: {buyer_name} ({organization})
Phone: {phone}
Product: {product_name}
Quantity: {quantity}
Delivery: {delivery_location}
Preferred supplier: {vendor_name}        [only when present]
Notes: {notes}                           [only when present]

— SocioMED
```

### New sales lead

```text
New buyer lead
Lead ID: {lead_id}
Buyer: {buyer_name}
Organization: {organization}
Phone: {phone}
Need: {use_case}                         [only when present]

— SocioMED
```

### Daily RFQ digest

```text
SocioMED daily RFQ digest (last 24h)
New RFQs: {count}
Status changes: {count}
Current statuses: {status} {count}, ...  [when present]

Zelus direct revenue (...)               [when present]
...

Zelus commission revenue (...)           [when present]
...

New requests:                            [when present]
#{rfq_id} {product_name} x{quantity} — {organization} [{status}]
```

## Complete flow reference

The state-by-state routing, global commands, intent order, search behavior, and test checklist are documented in `docs/WHATSAPP_CONVERSATION_LOGIC.md`.
