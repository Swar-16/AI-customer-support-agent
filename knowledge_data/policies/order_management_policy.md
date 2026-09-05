# ORDER MANAGEMENT POLICY

| Field | Value |
|---|---|
| **Policy Name** | Order Management Policy |
| **Effective Date** | August 28, 2026 |
| **Version** | 1.0 |
| **Policy Owner** | Customer Operations & Fulfillment |
| **Review Cycle** | Annual, or sooner if operational, legal, or regulatory requirements change |
| **Scope** | Standard consumer orders placed through Company-operated web, mobile, and customer-service channels |
| **Applies To** | Domestic and international merchandise orders unless a product, destination, or commercial agreement states otherwise |

## 1. General Overview & Eligibility Criteria

### 1.1 Purpose

This policy governs the creation, modification, status management, fulfillment, and escalation of customer orders placed with **Company**.

The policy establishes:

- A defined **order-change grace period**
- Standardized order-status definitions
- Rules for address, item, quantity, size, and color changes
- Controls for fraud prevention and fulfillment integrity
- Processing-time and financial rules
- Escalation and documentation requirements

### 1.2 Order-Change Grace Period

Customers may request modifications to an order during the **60-minute order-change grace period** beginning at the time the order is successfully submitted and payment authorization is obtained.

Changes may include:

| Change Type | Permitted During 60-Minute Grace Period? | Conditions |
|---|---:|---|
| Shipping address | **Yes** | New address must pass validation and fraud/risk checks |
| Billing address | **Yes** | Subject to payment-provider and fraud controls |
| Size | **Yes** | Requested size must be available |
| Color | **Yes** | Requested variant must be available |
| Item quantity | **Yes** | Inventory must remain available |
| Remove an item | **Yes** | Order must not have entered fulfillment |
| Add an item | **Yes** | Additional payment authorization may be required |
| Shipping method | **Yes** | Upgrade/downgrade subject to cutoff and availability |
| Delivery destination country | **Generally no** | Requires cancellation and creation of a new order |
| Payment method | **Limited** | Subject to payment-provider capabilities; support may require cancellation/reorder |

> **Critical rule:** The 60-minute grace period does not guarantee that an order can be changed. An order may enter fulfillment before 60 minutes when warehouse processing, inventory allocation, fraud review, carrier cutoff, or operational demand requires earlier release.

### 1.3 When the Grace Period Ends

The change window closes at the earlier of:

1. **60 minutes after successful order placement**, or
2. The moment the order is moved into **Processing** or another fulfillment-locked state.

After the order has entered fulfillment, Company will make reasonable efforts to accommodate requests, but **modification is not guaranteed**.

A customer may be required to use the applicable cancellation, return, exchange, or replacement process instead.

### 1.4 Eligibility Prerequisites

A modification request is eligible only when:

- The order number or other approved authentication details are provided.
- The request is made by the purchaser, an authorized account user, or a verified representative.
- The requested change does not violate product, destination, payment, export, sanctions, or fraud controls.
- Inventory is available for any replacement SKU or variant.
- The order has not been irrevocably transferred to the carrier.
- The revised order remains commercially and operationally serviceable.

### 1.5 Authentication Requirements

Customer support may request:

- Order number
- Customer name
- Email address or telephone number associated with the order
- Billing ZIP/postal code
- Last four digits of the payment instrument, where permitted

Company will not request or record a full card number, CVV, password, one-time authentication code, or other sensitive authentication secret through ordinary customer support channels.

### 1.6 Order Status Definitions

Order status reflects the latest operational state recorded in Company's order-management system.

| Status | Definition | Customer Changes |
|---|---|---|
| **Pending** | Order has been submitted but is awaiting payment confirmation, inventory allocation, fraud screening, or another initial validation step. | Usually permitted, subject to system controls |
| **Processing** | Payment and core validation are complete and fulfillment activity has started, including allocation, picking, packing, or warehouse release. | **Not guaranteed**; normally locked |
| **Shipped** | Package has been transferred to the designated carrier and a shipment/tracking event has been created. | No item/address changes |
| **Delivered** | Carrier records indicate the shipment was delivered to the designated destination or an approved delivery point. | No order modification; post-delivery support applies |
| **Cancelled** | Order has been cancelled before completion of fulfillment. | No further modification |
| **On Hold** | Order requires manual review due to payment, fraud, inventory, address, compliance, or operational issues. | Changes may be possible after review |
| **Partially Shipped** | At least one item has shipped while one or more remaining items are still pending fulfillment. | Unshipped items remain subject to applicable controls |
| **Exception** | Fulfillment or delivery has encountered a material issue requiring intervention. | Resolution depends on issue type |

### 1.7 Status Priority

Where multiple events occur close together, the Company's order-management system uses the **latest confirmed fulfillment state**.

A customer service message, email, or portal display may lag behind the operational system by up to **30 minutes**.

For disputes concerning the exact time an order entered fulfillment, Company records, including the order-management event log and warehouse event timestamp, are controlling absent evidence of a system error.

---

## 2. Step-by-Step Operating Procedures

### 2.1 Customer Procedure: Modify an Order

1. **Locate the order.** Retrieve the order confirmation email, account order history, or order number.
2. **Confirm the order status.** If the order remains **Pending**, modification is generally available.
3. **Submit the request immediately.** Contact customer support or use the self-service modification function, where available.
4. **Specify the exact change.** State the affected item/SKU and the requested new address, size, color, quantity, or shipping method.
5. **Complete authentication.** Provide requested non-sensitive verification information.
6. **Wait for confirmation.** Do not assume a requested modification has succeeded until Company confirms it.
7. **Review the revised order.** Verify address, items, quantities, taxes, shipping charges, and any price difference.
8. **Retain the confirmation.** The revised order confirmation is the authoritative customer-facing record.

### 2.2 Agent Procedure: Address Change

1. Authenticate the customer.
2. Determine whether the order is within the **60-minute grace period** and remains outside fulfillment lock.
3. Validate the requested address through Company's address-validation system.
4. Confirm that the destination is serviceable by the selected carrier and shipping method.
5. Run required fraud/risk screening.
6. Update the shipping address only if all required checks pass.
7. Recalculate shipping charges and taxes where applicable.
8. Record the modification timestamp, prior address status, reason code, and agent identifier.
9. Issue a revised confirmation to the customer.

An address change must be denied when the new destination is prohibited by:

- Carrier restrictions
- Product-specific shipping rules
- Export controls
- Sanctions or restricted-country controls
- Fraud/risk controls
- Warehouse release status

### 2.3 Agent Procedure: Size or Color Change

1. Authenticate the customer.
2. Confirm the order is eligible for modification.
3. Verify replacement inventory.
4. Confirm the requested SKU/variant.
5. If the replacement price differs, obtain customer approval where additional authorization or payment is required.
6. Release the original SKU allocation only after the new SKU is successfully reserved.
7. Update the order record.
8. Confirm the revised item details and expected fulfillment timing.

### 2.4 Agent Procedure: Quantity or Item Removal

1. Verify order status and fulfillment lock.
2. Confirm the exact line item and quantity.
3. Remove only quantities that have not entered an irrevocable fulfillment stage.
4. Recalculate subtotal, tax, shipping, discounts, and promotional thresholds.
5. If removal invalidates a promotion, disclose the revised pricing before completion where feasible.
6. Process any resulting refund or authorization adjustment according to Section 4.
7. Send revised order confirmation.

### 2.5 Agent Procedure: Add an Item

1. Verify that the order remains modifiable.
2. Confirm inventory.
3. Confirm item price and applicable tax/shipping changes.
4. Obtain additional payment authorization when required.
5. Add the item only after successful authorization or approved payment capture.
6. Confirm the revised total and fulfillment expectation.
7. Record the modification.

### 2.6 Cancellation Request After Fulfillment Lock

When cancellation is requested after an order enters **Processing**:

1. Verify the order's current state.
2. Attempt cancellation through the order-management system.
3. If cancellation is successful, issue confirmation and initiate applicable refund procedures.
4. If cancellation fails because fulfillment has progressed, explain that the order cannot be stopped through ordinary support.
5. Advise the customer of the applicable return or refusal-of-delivery process, if available.
6. Do not instruct a customer to create a duplicate order solely to circumvent a cancellation restriction without operational approval.

### 2.7 Partial-Shipment Handling

For orders containing multiple items:

1. Identify shipped and unshipped line items.
2. Confirm whether the customer request concerns the unshipped portion only.
3. Do not alter a shipped line item.
4. Apply changes to unshipped items only where the system permits.
5. Communicate separate delivery expectations where items are shipping independently.

---

## 3. Exceptions, Restrictions & Special Cases

### 3.1 Orders Entering Fulfillment Early

The 60-minute grace period is an outer limit, not a guaranteed processing delay.

Orders may become locked earlier because of:

- Warehouse workload
- Same-day or expedited shipping cutoff
- Automated inventory allocation
- Pick/pack initiation
- Carrier collection schedules
- Fraud screening
- Product-specific handling

Once fulfillment lock occurs, Company is not required to modify the order.

### 3.2 Fraud Prevention and Security Holds

Company may place an order on **On Hold** when transaction or account activity presents elevated risk.

Examples include:

- Billing/shipping mismatch
- Multiple failed payment attempts
- Unusual order value
- High-velocity orders
- Repeated account/device changes
- Suspected account takeover
- Known fraud indicators

A security hold may delay fulfillment by **up to 2 business days** while additional verification is completed.

Company may deny a modification if the requested change would materially increase fraud risk.

### 3.3 Restricted Products

Certain products may have stricter modification rules due to:

- Age restrictions
- Regulatory requirements
- Serial-number tracking
- Hazardous-material shipping rules
- Personalized production
- Digital delivery
- Hygiene or safety requirements

**Personalized, engraved, configured, or made-to-order products become non-modifiable once production begins.**

### 3.4 Non-Returnable or Non-Exchangeable Products

Changing an order does not override a separate product restriction.

Items designated as **non-refundable**, **final sale**, **custom-made**, **personalized**, or otherwise excluded from returns remain subject to their stated product terms.

### 3.5 Promotional Orders

Changes may affect promotions.

Examples:

- Removing a qualifying item may eliminate a bundle discount.
- Reducing quantity may invalidate a minimum-spend promotion.
- Adding an item does not automatically guarantee the original promotional price.
- Coupon or promotion eligibility is recalculated after an approved modification.

### 3.6 International Orders

International orders may be subject to:

- Import restrictions
- Customs requirements
- Destination-specific product prohibitions
- Duties and taxes
- Carrier service limits
- Address-format requirements

Changing an international destination generally requires **cancellation and placement of a new order**, because duties, taxes, export documentation, and shipping charges can change.

Company does not guarantee that customs duties or import taxes will be refundable after an order is shipped.

### 3.7 Enterprise and Contractual Orders

Orders placed under a negotiated enterprise, wholesale, reseller, or contractual agreement may have different:

- Modification windows
- Approval rules
- Pricing
- Payment terms
- Cancellation rights
- Shipment allocation rules

Where a signed commercial agreement conflicts with this policy, the **signed agreement controls** for the affected transaction.

### 3.8 Payment Failures

If payment authorization fails:

- Order status may remain **Pending** or change to **On Hold**.
- Inventory is not guaranteed to remain reserved indefinitely.
- Customer may be required to update payment details within **24 hours**.
- An expired authorization may require a new payment authorization before fulfillment.

### 3.9 Duplicate Orders

Customers who accidentally submit duplicate orders must contact Company promptly.

A duplicate order may be cancelled only if it has not reached fulfillment lock.

Company is not responsible for cancellation of a duplicate order that has already entered fulfillment.

### 3.10 Carrier Handoff

After an order reaches **Shipped**, Company cannot guarantee carrier-side changes to:

- Address
- Delivery date
- Delivery location
- Package contents

Any available carrier interception or redirect service depends on the carrier and may incur fees.

---

## 4. Processing Times, Fees & Financial Terms

### 4.1 Standard Operational Timelines

| Activity | Standard Target |
|---|---:|
| Order acknowledgment | Within **15 minutes** of successful submission |
| Order-change grace period | **60 minutes** from successful order placement |
| Manual fraud/security review | Up to **2 business days** |
| Standard warehouse processing | **1–2 business days** after order validation |
| Expedited order processing | Same business day when placed before applicable cutoff and inventory is available |
| Standard domestic delivery after shipment | **3–7 business days** |
| International delivery after shipment | Typically **5–12 business days**, excluding customs delays |
| Status-display synchronization | Up to **30 minutes** |
| Customer-service escalation response | Within **1 business day** |
| Refund initiation after approved cancellation | Typically within **2 business days** |

Business days exclude Saturdays, Sundays, and Company-recognized public holidays unless a specific service expressly states otherwise.

### 4.2 Modification Fees

Company does not charge a standard **order-modification fee** when an eligible change is completed during the 60-minute grace period.

A customer may nevertheless be charged or credited for the underlying commercial difference.

| Transaction Effect | Financial Treatment |
|---|---|
| More expensive replacement item | Additional payment authorization/capture may be required |
| Less expensive replacement item | Difference may be refunded or credited according to the original payment method |
| Higher shipping cost | Additional shipping amount may apply |
| Lower shipping cost | Difference may be refunded where operationally supported |
| Address change altering duties/taxes | Revised amount may apply |
| Carrier redirect after shipment | Carrier fee may apply |

### 4.3 Refund Timing for Order Changes

Where an approved modification produces a refund:

1. Company initiates the refund, ordinarily within **2 business days** after approval.
2. The financial institution or payment processor controls the final posting time.
3. Card refunds commonly appear within **3–10 business days** after initiation.
4. Alternative payment methods may have different settlement times.

Company does not treat a payment processor's posting delay as a failure to initiate the refund.

### 4.4 Currency Handling

For international orders:

- Refunds are ordinarily processed in the currency of the original transaction.
- Exchange-rate movements between purchase and refund may cause the amount received in the customer's local currency to differ.
- Company does not guarantee reimbursement of foreign-exchange losses caused by exchange-rate movement unless required by applicable law.
- Duties, taxes, and customs fees may be administered by third parties and may have separate refund rules.

### 4.5 Price Changes

An approved modification may recalculate the order based on the applicable price at the time the modification is processed unless Company expressly preserves the original price.

Price protection is not automatic.

### 4.6 Restocking or Processing Charges

No general restocking fee applies solely to an eligible order modification completed before fulfillment lock.

Any product-specific restocking, cancellation, manufacturing, or processing fee must be disclosed under the applicable product or transaction terms.

---

## 5. Escalations & Customer Responsibilities

### 5.1 When to Escalate

An agent must escalate an order when:

- The customer disputes the recorded fulfillment-lock timestamp.
- A modification was confirmed but was not applied.
- An incorrect address was changed due to a confirmed Company error.
- An order has been incorrectly marked **Delivered**.
- A system error caused duplicate authorization or capture.
- A high-value or enterprise order requires manual intervention.
- Fraud/security review exceeds **2 business days** without a documented reason.
- A regulatory or international-shipping issue cannot be resolved at Tier 1.

### 5.2 Escalation Levels

| Level | Owner | Target Response |
|---|---|---:|
| **Tier 1** | Customer Support | Same interaction where possible |
| **Tier 2** | Order Operations | Within **1 business day** |
| **Tier 3** | Payments, Fraud, Logistics, or Compliance | Within **2 business days** |
| **Executive/Legal Review** | Authorized senior team | Case-specific |

### 5.3 Required Customer Documentation

Depending on the dispute, Company may require:

- Order number
- Order confirmation
- Photographs of incorrect or damaged packaging
- Delivery confirmation
- Carrier tracking information
- Proof of address where an address issue is disputed
- Payment transaction reference
- Written explanation of the requested resolution

Customers should not send full payment-card numbers, passwords, CVVs, or authentication codes.

### 5.4 Customer Responsibilities

Customers are responsible for:

- Providing accurate delivery information
- Reviewing the order confirmation promptly
- Requesting changes during the **60-minute grace period**
- Monitoring order status
- Responding promptly to payment or verification requests
- Ensuring someone can receive the package when required
- Preserving relevant documentation for disputed transactions

### 5.5 Company Error

Where Company demonstrably caused an incorrect shipment, unauthorized order modification, duplicate charge, or materially incorrect order record, Company will prioritize corrective action and may provide one or more of the following as appropriate:

- Corrected shipment
- Replacement
- Refund
- Shipping reimbursement
- Carrier intervention
- Account credit

Any remedy remains subject to applicable law and the facts of the individual case.

### 5.6 Finality of Operational Records

The following records may be used to determine the authoritative history of an order:

- Order creation timestamp
- Payment authorization timestamp
- Fulfillment-lock timestamp
- Warehouse scan events
- Shipment-confirmation timestamp
- Carrier acceptance event
- Delivery event
- Agent modification audit log

Customer-visible timestamps may differ from internal event times by up to **30 minutes** because of system synchronization.

### 5.7 Policy Interpretation

This policy defines Company's standard operational rules. It does not restrict any mandatory rights or remedies that cannot lawfully be excluded or limited under applicable consumer-protection, payment, privacy, or other law.

Where a specific jurisdiction grants a customer greater rights than this policy provides, the mandatory legal requirement controls.