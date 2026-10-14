module ArithmeticChecks

open Expecto

let tests =
    testList "arithmetic" [
        testCase "addition" <| fun _ -> Expect.equal (2 + 3) 5 "addition"
        testCase "multiplication" <| fun _ -> Expect.equal (4 * 3) 12 "multiplication"
        testCase "negative" <| fun _ -> Expect.equal (-2 + 1) -1 "negative"
    ]
