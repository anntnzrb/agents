module Examples
open Expecto
let suite =
    testCase "example" (fun _ ->
        Expect.equal (Transform.rotateLeft 1 [1; 2; 3]) [2; 3; 1] "rotate once")
