namespace Billing

module Amounts =
    let withTax subtotal taxRate = subtotal * (1M + taxRate)
