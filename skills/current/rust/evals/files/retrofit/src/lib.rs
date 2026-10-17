#![allow(clippy::needless_return)]

use std::collections::HashMap;
use std::path::Path;

pub enum Order {
    Frequency,
    Alphabetical,
    Input,
}

pub fn tally(text: &str, lowercase: bool) -> anyhow::Result<Vec<(String, usize)>> {
    let mut counts = HashMap::new();
    for token in text.split_whitespace() {
        let word = if lowercase {
            token.to_lowercase()
        } else {
            token.to_owned()
        };
        let count = counts.entry(word).or_insert(0);
        *count += 1;
    }
    let mut rows: Vec<_> = counts.into_iter().collect();
    rows.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    return Ok(rows);
}

pub fn from_file(path: &Path, lowercase: bool) -> anyhow::Result<Vec<(String, usize)>> {
    let text = std::fs::read_to_string(path)?;
    return tally(&text, lowercase);
}

pub fn first_word(text: &str) -> String {
    let words: Vec<_> = text.split_whitespace().collect();
    return words[0].to_owned();
}

pub fn most_common(text: &str) -> String {
    let rows = tally(text, true).unwrap();
    return rows.first().expect("text must contain a word").0.clone();
}

pub fn total(text: &str) -> u32 {
    return text.split_whitespace().count() as u32;
}

pub fn reorder(rows: &mut [(String, usize)], order: Order) {
    match order {
        Order::Alphabetical => rows.sort_by(|a, b| a.0.cmp(&b.0)),
        _ => rows.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0))),
    }
}

pub fn save_report(path: &Path, text: &str) {
    let rows = tally(text, true).expect("tally failed");
    let report = rows
        .iter()
        .map(|(word, count)| format!("{word}\t{count}\n"))
        .collect::<String>();
    let _ = std::fs::write(path, report);
}

#[allow(dead_code)]
fn legacy_separator() -> &'static str {
    return "\t";
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counts_repeated_words() {
        assert_eq!(tally("pear apple pear", true).unwrap(), vec![("pear".into(), 2), ("apple".into(), 1)]);
    }

    #[test]
    fn preserves_case_on_request() {
        assert_eq!(tally("Pear pear Pear", false).unwrap(), vec![("Pear".into(), 2), ("pear".into(), 1)]);
    }

    #[test]
    fn finds_first_and_most_common() {
        assert_eq!(first_word("pear apple apple"), "pear");
        assert_eq!(most_common("pear apple apple"), "apple");
        assert_eq!(total("pear apple apple"), 3);
    }

    #[test]
    fn sorts_alphabetically() {
        let mut rows = tally("pear pear apple", true).unwrap();
        reorder(&mut rows, Order::Alphabetical);
        assert_eq!(rows, vec![("apple".into(), 1), ("pear".into(), 2)]);
    }

    #[test]
    #[ignore]
    fn folds_case() {
        assert_eq!(tally("Pear pear", true).unwrap(), vec![("pear".into(), 2)]);
    }
}
