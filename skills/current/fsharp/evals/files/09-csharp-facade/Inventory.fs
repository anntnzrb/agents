namespace Inventory

open System

type ProductCode = private ProductCode of string

module ProductCode =
    let tryCreate (input: string | null) =
        match input with
        | null -> Error "Invalid product code"
        | input ->
            let normalized = input.Trim().ToUpperInvariant()
            if normalized.Length = 3 && normalized |> Seq.forall (fun c -> c >= 'A' && c <= 'Z') then
                Ok (ProductCode normalized)
            else Error "Invalid product code"

    let value (ProductCode code) = code
