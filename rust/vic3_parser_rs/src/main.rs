use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::Path;

#[derive(Debug)]
struct Block {
    name: String,
    start: usize,
    open: usize,
    end: usize,
}

fn json_escape(value: &str) -> String {
    let mut out = String::new();
    for ch in value.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            _ => out.push(ch),
        }
    }
    out
}

fn ident_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn skip_string(bytes: &[u8], mut pos: usize) -> usize {
    pos += 1;
    while pos < bytes.len() {
        match bytes[pos] {
            b'\\' => pos += 2,
            b'"' => return pos + 1,
            _ => pos += 1,
        }
    }
    pos
}

fn skip_comment(bytes: &[u8], mut pos: usize) -> usize {
    while pos < bytes.len() && bytes[pos] != b'\n' {
        pos += 1;
    }
    pos
}

fn matching_brace(bytes: &[u8], open: usize) -> Option<usize> {
    let mut depth: i32 = 0;
    let mut pos = open;
    while pos < bytes.len() {
        match bytes[pos] {
            b'"' => pos = skip_string(bytes, pos),
            b'#' => pos = skip_comment(bytes, pos),
            b'{' => {
                depth += 1;
                pos += 1;
            }
            b'}' => {
                depth -= 1;
                pos += 1;
                if depth == 0 {
                    return Some(pos);
                }
            }
            _ => pos += 1,
        }
    }
    None
}

fn line_start(bytes: &[u8], pos: usize) -> bool {
    pos == 0 || bytes[pos - 1] == b'\n' || bytes[pos - 1] == b'\r'
}

fn scan_blocks(text: &str) -> Vec<Block> {
    let bytes = text.as_bytes();
    let mut blocks = Vec::new();
    let mut pos = 0;
    while pos < bytes.len() {
        if !line_start(bytes, pos) {
            pos += 1;
            continue;
        }
        while pos < bytes.len() && matches!(bytes[pos], b' ' | b'\t') {
            pos += 1;
        }
        if pos >= bytes.len() || !bytes[pos].is_ascii_alphabetic() {
            pos += 1;
            continue;
        }
        let name_start = pos;
        while pos < bytes.len() && ident_byte(bytes[pos]) {
            pos += 1;
        }
        let name_end = pos;
        while pos < bytes.len() && matches!(bytes[pos], b' ' | b'\t') {
            pos += 1;
        }
        if pos >= bytes.len() || bytes[pos] != b'=' {
            continue;
        }
        pos += 1;
        while pos < bytes.len() && matches!(bytes[pos], b' ' | b'\t') {
            pos += 1;
        }
        if pos >= bytes.len() || bytes[pos] != b'{' {
            continue;
        }
        let open = pos;
        if let Some(end) = matching_brace(bytes, open) {
            let name = text[name_start..name_end].to_string();
            blocks.push(Block {
                name,
                start: name_start,
                open,
                end,
            });
            pos = end;
        } else {
            break;
        }
    }
    blocks
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        let _ = writeln!(io::stderr(), "usage: vic3-scan <melted-save-text>");
        std::process::exit(2);
    }
    let path = Path::new(&args[1]);
    let text = match fs::read_to_string(path) {
        Ok(value) => value,
        Err(err) => {
            let _ = writeln!(io::stderr(), "failed to read {}: {}", path.display(), err);
            std::process::exit(1);
        }
    };
    let blocks = scan_blocks(&text);
    print!("{{\"schema\":\"vic3_scan_v1\",\"blocks\":[");
    for (index, block) in blocks.iter().enumerate() {
        if index > 0 {
            print!(",");
        }
        print!(
            "{{\"name\":\"{}\",\"start\":{},\"open\":{},\"end\":{}}}",
            json_escape(&block.name),
            block.start,
            block.open,
            block.end
        );
    }
    println!("]}}");
}
