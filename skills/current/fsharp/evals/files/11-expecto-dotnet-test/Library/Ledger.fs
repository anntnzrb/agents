module Ledger

let total (entries: int list) = List.sum entries
let credit amount balance = balance + amount
