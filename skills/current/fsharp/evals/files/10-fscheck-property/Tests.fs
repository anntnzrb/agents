module Tests
open Expecto
[<Tests>]
let suite = testList "rotation" [Examples.suite]
[<EntryPoint>]
let main argv = runTestsWithCLIArgs [] argv suite
