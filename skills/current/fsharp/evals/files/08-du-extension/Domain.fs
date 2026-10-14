namespace Jobs

type Job =
    | Cached of int
    | Remote of string
    | Ignored
