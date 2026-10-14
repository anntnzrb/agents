module Checks

open Expecto
open FsCheck

[<Tests>]
let tests =
    testList "ledger" [
        testCase "empty total" <| fun _ -> Expect.equal (Ledger.total []) 0 "empty"
        testCase "credit" <| fun _ -> Expect.equal (Ledger.credit 7 5) 12 "credit"
        testProperty "singleton total" <| fun (value: int) ->
            Prop.forAll (Arb.from<int>) (fun _ -> Ledger.total [value] = value)
    ]
