from aingram.governance.secrets import scan_for_secrets


def test_clean_text_has_no_hits():
    assert scan_for_secrets('a normal memory about the venv') == []


def test_anthropic_key_is_caught():          # the gap in the fork's default set
    fake = 'sk-' + 'ant-' + 'api03-' + 'A' * 24   # split literal: commit no key-shaped string
    assert scan_for_secrets(f'key {fake}') != []


def test_supabase_key_is_caught():
    assert scan_for_secrets('SUPABASE_KEY=eyJhbGciOiJIUzI1Ni') != []


def test_openai_style_key_still_caught():     # inherited from the fork's set
    assert scan_for_secrets('sk-ABCDEFGHIJKLMNOPQRSTUV12') != []


def test_content_hash_is_not_flagged():       # 64-hex hash must NOT trip the R2 heuristic
    h = 'a3f' * 21 + 'b'                       # 64-char hex — the shape of every content_hash
    assert scan_for_secrets(f'see entry with content_hash {h}') == []


def test_base64_signature_is_not_flagged():   # Ed25519 sig is long base64; must NOT trip
    sig = 'A' * 88                            # base64 of a 64-byte signature
    assert scan_for_secrets(f'signature={sig}') == []   # not a *_SECRET_*_KEY assignment


def test_r2_secret_assignment_is_caught():    # the real secret, in key-assignment context
    assert scan_for_secrets('R2_SECRET_ACCESS_KEY=' + 'k' * 40) != []
