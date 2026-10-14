namespace Jobs

module Dispatch =
    let run (fetch: string -> string) job =
        match job with
        | Cached value when value >= 0 -> string value
        | Remote key -> fetch key
        | _ -> "ignored"
