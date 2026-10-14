namespace PinnedReads

module Reader =
    let readBoth (left: unit -> Async<string>) (right: unit -> Async<string>) : Async<string * string> =
        async {
            let! first = left ()
            let! second = right ()
            return first, second
        }
