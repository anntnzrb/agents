namespace Billing

open System

module Invoice =
    let total subtotal taxRate =
        Math.Round(Amounts.withTax subtotal taxRate, 2)
