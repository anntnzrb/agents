use std::process::Command;

#[test]
fn prints_top_five_words() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("target").join(format!("tally-cli-{}.txt", std::process::id()));
    std::fs::write(&path, "pear pear pear apple apple banana cherry date fig").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_tally")).arg(&path).output().unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8(output.stdout).unwrap(), "1. pear\t3\n2. apple\t2\n3. banana\t1\n4. cherry\t1\n5. date\t1\n");
}

#[test]
fn reports_missing_file() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("target").join(format!("tally-absent-{}/input.txt", std::process::id()));
    let output = Command::new(env!("CARGO_BIN_EXE_tally")).arg(&path).output().unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8(output.stderr).unwrap().contains("No such file or directory"));
}
