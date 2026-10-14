namespace People

type Person = { Name: string; Age: int }

module Boundary =
    let decode (_json: string) : Result<Person, string> =
        Error "Not implemented"
