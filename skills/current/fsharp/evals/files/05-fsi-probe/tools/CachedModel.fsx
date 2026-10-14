module CachedInvoice

let total subtotal taxRate =
    System.Math.Round(subtotal * (1M + taxRate), 2, System.MidpointRounding.ToPositiveInfinity)
