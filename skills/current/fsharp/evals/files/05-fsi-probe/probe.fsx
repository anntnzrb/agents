#load "tools/CachedModel.fsx"

let actual = CachedInvoice.total 1.005M 0M
printfn "Invoice total: %M" actual
if actual <> 1.01M then failwith "Unexpected invoice total"
