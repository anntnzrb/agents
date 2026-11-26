# Data Modeling



## Section index


# BAD: validate then pass raw data
def process_email(email: str) -> None:
    if "@" not in email:
        raise ValueError("invalid email")
    # still a raw str everywhere downstream


# GOOD: parse into typed value at boundary
from typing import NewType

Email = NewType("Email", str)


def parse_email(raw: str) -> Email:
    if "@" not in raw or "." not in raw.split("@")[1]:
        msg = f"invalid email: {raw}"
        raise ValueError(msg)
    return Email(raw.lower().strip())


# Downstream only sees Email, never raw str
def send_welcome(email: Email) -> None: ...
```

With Pydantic this happens automatically; `EmailStr` is already a parsed type. Once constructed, `.email` is always valid. No re-validation needed.

---

## Sources

- Python docs: [dataclasses](https://docs.python.org/3/library/dataclasses.html)
- Pydantic v2: [docs.pydantic.dev](https://docs.pydantic.dev/latest/)
- Python docs: [typing; Protocol](https://docs.python.org/3/library/typing.html#typing.Protocol)
- Python docs: [typing; TypedDict](https://docs.python.org/3/library/typing.html#typing.TypedDict)
- Alexis King: [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/)
