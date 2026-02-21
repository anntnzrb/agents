#!/usr/bin/env -S cargo -Zscript
---cargo
[package]
name = "script"
edition = "2024"

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
---

use serde::Serialize;

#[derive(Serialize)]
struct Message {
    text: String,
}

fn main() {
    let msg = Message {
        text: "hello from cargo script".to_string(),
    };
    println!("{}", serde_json::to_string_pretty(&msg).unwrap());
}
