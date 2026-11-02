"""Webcam capture for passport photos: camera allowed for this site only; uploads still validated server-side."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, setup_module, teardown_module  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_permissions_policy_allows_camera_for_self_only():
    pp = A.app.test_client().get('/login').headers['Permissions-Policy']
    assert 'camera=(self)' in pp and 'microphone=()' in pp and 'geolocation=()' in pp


def test_camera_script_is_external_and_wired():
    js = (ROOT / 'static/app.js').read_text()
    assert 'getUserMedia' in js and 'passport_photo' in js and 'DataTransfer' in js
    assert '.cam-panel' in (ROOT / 'static/style.css').read_text()
    csp = A.app.test_client().get('/login').headers['Content-Security-Policy']
    assert "script-src 'self'" in csp and 'unsafe-inline' not in csp.split('script-src')[1].split(';')[0]
