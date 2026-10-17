use std::path::Path;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).expect("usage: tally <path>");
    let rows = tally::from_file(Path::new(path), true)?;
    print_top(&rows);
    Ok(())
}

fn print_top(rows: &[(String, usize)]) {
    if rows.is_empty() {
        println!("No words found");
        return;
    }

    let limit = 5;
    for (index, (word, count)) in rows.iter().take(limit).enumerate() {
        print_row(index + 1, word, *count);
    }
}

fn print_row(rank: usize, word: &str, count: usize) {
    println!("{rank}. {word}\t{count}");
}
