module Ownership

open System.Threading
open System.Threading.Tasks

let runBoth (first: CancellationToken -> Task<int>) (second: CancellationToken -> Task<int>) (token: CancellationToken) : Task<int * int> =
    task {
        let! a = first token
        let! b = second token
        return a, b
    }
