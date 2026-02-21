#!/usr/bin/env -S cargo -Zscript
---cargo
[package]
name = "async-script"
edition = "2024"

[dependencies]
tokio = { version = "1", features = ["rt-multi-thread", "macros"] }
reqwest = { version = "0.12", features = ["json"] }
serde = { version = "1", features = ["derive"] }
---

use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct IpResponse {
    origin: String,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let data: IpResponse = reqwest::get("https://httpbin.org/ip").await?.json().await?;
    println!("{}", data.origin);
    Ok(())
}
