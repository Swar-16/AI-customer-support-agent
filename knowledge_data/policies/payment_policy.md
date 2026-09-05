# Payment Policy

## Header Block

| Field | Value |
|---|---|
| **Policy Name** | Payment Policy |
| **Policy Domain** | PAYMENT |
| **Effective Date** | 2026-08-28 |
| **Version** | 1.0 |
| **Policy Owner** | Finance & Payments Operations |
| **Review Cycle** | Annual, or sooner following material regulatory, banking, or payment-provider changes |
| **Applies To** | Standard, Business, and Enterprise customers |
| **Scope** | Customer payments, payment authorization, payment capture, payment failures, payment methods, currency conversion, payment disputes, and payment security |

> **Critical rule:** A payment is considered successfully completed only after the Company or its authorized payment processor confirms the transaction as **captured/settled**. A bank debit, pending card authorization, or payment-screen confirmation alone does not necessarily mean that the Company has received the funds.

---

## 1. General Overview & Eligibility Criteria

### 1.1 Purpose

This policy establishes the rules and procedures governing payments made to the Company for products, subscriptions, services, usage-based charges, and other approved transactions.

The policy applies regardless of whether payment is initiated through:

- Credit or debit card
- UPI
- Bank transfer
- Approved digital-wallet method
- Payment link
- Other payment methods explicitly enabled for the customer's account

### 1.2 Payment Eligibility

A customer may make a payment when:

1. The customer's account is active and not suspended for payment-related reasons.
2. The selected payment method is supported for the customer's billing country.
3. The payment amount does not exceed applicable transaction or account limits.
4. The payment instrument has sufficient funds or available credit.
5. Required authentication, including 3-D Secure, OTP, UPI authorization, or bank authentication, is successfully completed.
6. The transaction passes applicable fraud, sanctions, compliance, and risk controls.
7. The customer's billing information is sufficiently complete to process the transaction.

### 1.3 Payment Currency

Unless the applicable order, invoice, or commercial agreement states otherwise:

- Prices are displayed in the currency configured for the customer's billing account.
- The Company may support multiple currencies depending on customer location and payment method.
- The final amount charged is the amount presented at checkout or stated on the applicable invoice before payment authorization.
- A customer's bank, card issuer, wallet provider, or intermediary financial institution may independently apply foreign-exchange rates or fees.

### 1.4 Payment Authorization and Capture

A payment can pass through multiple states:

| Payment State | Meaning | Customer Action |
|---|---|---|
| **Initiated** | Customer has started checkout | Complete payment flow |
| **Pending** | Payment provider has not provided final confirmation | Do not repeatedly submit unless instructed |
| **Authorized** | Payment instrument has approved the transaction | No action unless payment later fails |
| **Captured** | Company/payment processor has successfully captured funds | Payment is considered successful |
| **Settled** | Funds have completed settlement to the Company/payment processor | No action required |
| **Failed** | Payment could not be completed | Retry or use another method |
| **Declined** | Issuer or processor rejected the transaction | Contact issuer or use another method |
| **Canceled** | Transaction was canceled before capture | Initiate a new payment if required |
| **Reversed** | Previously authorized amount was released/reversed | No duplicate payment unless instructed |

### 1.5 Duplicate Payment Prevention

Customers must not submit the same payment repeatedly while a transaction is marked **Pending**.

If a payment remains pending, the customer should wait at least **15 minutes** before attempting another payment unless the checkout system explicitly instructs otherwise.

If two successful payments are made for the same invoice, the customer must contact Payments Support with both transaction references.

---

## 2. Step-by-Step Operating Procedures

### 2.1 Standard Online Payment Procedure

1. Sign in to the Company account.
2. Open the applicable invoice, order, subscription, or payment request.
3. Verify:
   - Amount due
   - Currency
   - Invoice/order number
   - Billing details
   - Payment deadline
4. Select an available payment method.
5. Enter or confirm the required payment information.
6. Complete any required authentication, such as OTP, 3-D Secure, UPI approval, or bank authentication.
7. Wait for the payment processor to return a final status.
8. Confirm that the transaction is shown as **Successful**, **Captured**, or an equivalent completed status.
9. Retain the payment confirmation and transaction/reference ID.

> **Do not close the payment page or submit the payment again merely because the confirmation screen takes several seconds to load.** Duplicate submissions can create additional authorizations or duplicate charges.

### 2.2 Card Payment Procedure

For card payments:

1. Enter the card number, expiry date, and security code where requested.
2. Confirm the billing information.
3. Complete 3-D Secure, OTP, or other issuer authentication when required.
4. Wait for the final transaction result.
5. If the payment is declined, verify the decline reason if displayed.
6. If the reason is not provided, contact the card issuer or retry using another supported payment method.

The Company does not store full card numbers or CVV/security codes when payment processing is handled by an authorized payment processor.

### 2.3 UPI Payment Procedure

For UPI-enabled transactions:

1. Select UPI at checkout.
2. Choose the supported UPI application or enter the requested UPI identifier.
3. Confirm the payment in the UPI application.
4. Complete UPI authentication.
5. Return to the Company checkout page.
6. Wait for the final payment status.

If the bank account is debited but the Company still displays the transaction as **Pending**, do not immediately submit another payment.

Wait at least **30 minutes** and then check the invoice/payment status again.

### 2.4 Bank Transfer Procedure

For bank transfers:

1. Obtain the bank details displayed on the Company's official invoice or payment instructions.
2. Initiate the transfer for the exact invoiced amount.
3. Include the required invoice number or payment reference.
4. Retain the bank transaction confirmation.
5. Allow the applicable processing period for the payment to be matched.
6. Contact Payments Support if the payment is not reflected after the applicable processing window.

Customers must not transfer funds to bank details received from an unverified third party.

### 2.5 Payment Failure Procedure

If a payment fails:

1. Record the displayed error message and transaction/reference ID.
2. Check whether the payment was actually debited.
3. If **not debited**, retry once after correcting the identified issue.
4. If the retry fails, use another supported payment method where available.
5. If the customer's account was debited despite a failed status, do not submit repeated payments.
6. Contact Payments Support with:
   - Invoice/order number
   - Transaction/reference ID
   - Payment date and approximate time
   - Amount and currency
   - Payment method
   - Screenshot or error message, where available

### 2.6 Payment Confirmation Procedure

A customer should retain the following information until the payment is fully reconciled:

- Invoice or order number
- Transaction/reference ID
- Payment date
- Amount
- Currency
- Payment method
- Payment confirmation or receipt

For business and enterprise accounts, the Company may additionally require the customer's purchase order number or internal payment reference.

---

## 3. Exceptions, Restrictions & Special Cases

### 3.1 Fraud and Risk Controls

The Company may delay, reject, reverse, or request additional verification for transactions that trigger payment-risk controls.

Examples include:

- Unusual transaction amounts
- Multiple failed payment attempts
- Multiple cards used against the same account
- Billing-country and payment-instrument inconsistencies
- High-risk IP, device, or transaction characteristics
- Suspected unauthorized use
- Suspected account takeover
- Suspected payment fraud

A risk review may take up to **24 hours** after the transaction is flagged.

The Company may request additional information before allowing the transaction to proceed.

### 3.2 Velocity and Retry Restrictions

Repeated payment attempts can trigger automated controls.

As a standard operational safeguard:

- More than **5 failed payment attempts within 30 minutes** may trigger a temporary payment restriction.
- The restriction may last up to **24 hours**.
- Customers should not attempt to bypass a restriction by creating duplicate accounts or repeatedly changing payment instruments.

### 3.3 Insufficient Funds or Credit

A payment may fail when:

- The bank account lacks sufficient funds.
- Available card credit is insufficient.
- The payment method has expired.
- The issuer has blocked the transaction.
- The transaction exceeds an issuer limit.
- The customer has not completed required authentication.

The Company cannot override an issuer's decision.

### 3.4 International Payments

International transactions may be subject to:

- Foreign-exchange conversion
- Issuer fees
- Cross-border transaction fees
- Intermediary-bank fees
- Local banking restrictions
- Additional authentication
- Local regulatory requirements

The Company is responsible only for fees explicitly identified as Company-imposed fees.

Bank, card-network, intermediary-bank, wallet-provider, and issuer fees may be outside the Company's control.

### 3.5 Currency Conversion

When currency conversion is required:

1. The applicable checkout or invoice amount is displayed before authorization whenever practicable.
2. The payment processor may perform the actual currency conversion.
3. The customer's financial institution may use a different exchange rate.
4. The customer's final account statement may therefore differ from an indicative converted amount displayed by the Company.

Any Company-defined conversion rate used for invoicing will be stated on the applicable invoice or checkout page.

### 3.6 Tax and Government Charges

Applicable taxes, duties, levies, or government-imposed charges may be added to the transaction where required by law or the applicable commercial agreement.

Tax treatment may vary by:

- Billing jurisdiction
- Customer type
- Tax registration status
- Product/service category
- Applicable law

Customers are responsible for providing accurate billing and tax information.

### 3.7 Enterprise Payment Terms

Enterprise customers may have payment terms that differ from standard customers under a signed commercial agreement.

Where an executed enterprise agreement conflicts with this policy, the **executed agreement controls to the extent of the conflict**.

Possible enterprise terms include:

- Net 15
- Net 30
- Net 45
- Net 60
- Purchase-order-based billing
- Invoice payment by bank transfer
- Contract-specific payment milestones

Enterprise customers must follow the payment terms specified in their agreement and invoice.

### 3.8 Non-Standard Payment Arrangements

Customers may not:

- Split a payment across unsupported payment methods.
- Deduct unauthorized fees from an invoice.
- Alter invoice amounts.
- Use another customer's payment credentials without authorization.
- Send funds to unofficial bank accounts.
- Mark an invoice as paid solely because a transfer was initiated.

---

## 4. Processing Times, Fees & Financial Terms

### 4.1 Standard Processing Times

| Payment Method | Typical Confirmation | Operational Maximum / Escalation Point |
|---|---:|---:|
| Credit/Debit Card | Usually within minutes | 24 hours if risk review applies |
| UPI | Usually within minutes | 30 minutes before first reconciliation check |
| Digital Wallet | Usually within minutes | 24 hours if provider confirmation is delayed |
| Domestic Bank Transfer | 1–2 business days | 3 business days |
| International Bank Transfer | 2–5 business days | 7 business days |
| Enterprise Invoice | Per contractual terms | Per applicable agreement |

Processing times are estimates and can be affected by weekends, bank holidays, intermediary banks, payment-provider outages, fraud reviews, or regulatory checks.

### 4.2 Payment Fees

Unless expressly stated at checkout, on the invoice, or in an applicable agreement, the Company does not add a separate standard payment-processing fee.

| Fee Type | Standard Treatment |
|---|---|
| Company payment-processing fee | None unless disclosed |
| Card issuer fee | Customer's responsibility |
| Foreign-exchange fee charged by bank | Customer's responsibility |
| Intermediary-bank fee | Customer's responsibility unless contract states otherwise |
| Chargeback/dispute fee | May apply where permitted by contract/law |
| Bank-transfer fee | Generally customer/bank responsibility |
| Tax or government levy | Applied where legally required |

### 4.3 Bank Transfer Reconciliation

Bank-transfer payments must contain the correct invoice or payment reference.

If a transfer cannot be matched automatically, Payments Operations may require proof of payment.

Manual reconciliation generally occurs within **1 business day** after sufficient payment evidence is received.

### 4.4 Payment Authorization Holds

A card issuer may place an authorization hold before funds are captured.

An authorization hold:

- Is not necessarily a completed payment.
- May temporarily reduce available credit.
- May remain visible after a failed or canceled transaction.
- Is released according to the issuer's policies.

The Company cannot guarantee the exact time an issuer will release an authorization hold.

### 4.5 Receipts and Invoices

For successful payments, the Company may issue an electronic payment receipt or update the applicable invoice status.

Enterprise customers may receive invoices according to their contractual billing schedule.

Customers should report incorrect invoice information within **30 calendar days** of invoice issuance.

---

## 5. Escalations & Customer Responsibilities

### 5.1 When to Contact Payments Support

Customers should contact Payments Support when:

- A payment was debited but remains failed or pending.
- A successful payment is not reflected against an invoice.
- The same invoice was charged more than once.
- A payment was made to an incorrect invoice.
- A bank transfer cannot be matched.
- A payment remains unresolved beyond the stated processing window.
- The customer believes an unauthorized payment occurred.

### 5.2 Required Payment Investigation Information

The customer should provide:

1. Account email or account identifier.
2. Invoice/order number.
3. Transaction/reference ID.
4. Payment amount.
5. Currency.
6. Payment method.
7. Date and approximate transaction time.
8. Bank/payment-provider reference, if available.
9. Screenshot or receipt showing the transaction status, where appropriate.

> **Never send a full card number, CVV/security code, PIN, UPI PIN, password, or one-time authentication code to Customer Support.**

### 5.3 Duplicate Payment Escalation

For suspected duplicate payments:

1. Do not make another payment.
2. Collect both transaction/reference IDs.
3. Contact Payments Support.
4. Payments Operations will compare the transactions against the invoice.
5. If both payments were captured and are confirmed as duplicates, the Company will process the applicable correction according to the Company's refund/credit procedures.

### 5.4 Unauthorized Payment Escalation

If a customer believes a payment was unauthorized:

1. Immediately secure the affected account.
2. Contact the payment provider or issuing bank where appropriate.
3. Contact the Company Payments Support team.
4. Provide the transaction/reference ID and transaction date.
5. Do not disclose passwords, PINs, CVVs, or OTPs to support personnel.

The Company may temporarily restrict an account or payment method while an investigation is conducted.

### 5.5 Chargebacks and Payment Disputes

A customer should first contact Payments Support when a payment appears incorrect or duplicated.

Where a card-network or payment-provider dispute is initiated, the Company may submit transaction records and other permitted evidence to the applicable payment provider.

Customers must provide requested documentation within the stated deadline.

### 5.6 Customer Responsibilities

Customers are responsible for:

- Providing accurate billing information.
- Maintaining valid payment credentials.
- Ensuring sufficient funds or credit.
- Completing required authentication.
- Using only payment methods they are authorized to use.
- Reviewing the amount and currency before authorization.
- Protecting payment credentials and authentication codes.
- Promptly reporting suspected unauthorized transactions.
- Retaining transaction records until payment reconciliation is complete.

### 5.7 Policy Precedence

If this policy conflicts with:

1. Applicable law or regulation;
2. A signed enterprise/commercial agreement; or
3. A specific transaction's disclosed payment terms;

the higher-priority document or legal requirement controls to the extent of the conflict.

The Company may amend this policy when operational, regulatory, banking, or payment-provider requirements change. Material changes will be communicated through the Company's standard customer-communication channels.