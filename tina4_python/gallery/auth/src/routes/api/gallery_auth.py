"""Gallery: Auth — JWT login with a visual demo page."""
from tina4_python.core.router import get, post, noauth
from tina4_python.auth import Auth


@noauth()
@get("/gallery/auth")
async def gallery_auth_page(request, response):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Auth Demo</title><link rel="stylesheet" href="/css/tina4.min.css">
</head>
<body class="bg-dark text-light">
<div class="container mt-5" style="max-width:600px;">
    <h2 class="mb-4">JWT Authentication Demo</h2>
    <div class="card mb-4">
        <div class="card-header bg-primary text-white">Login</div>
        <div class="card-body">
            <div class="form-group mb-3">
                <label class="form-label">Username</label>
                <input type="text" id="username" class="form-control" placeholder="admin" value="admin">
            </div>
            <div class="form-group mb-3">
                <label class="form-label">Password</label>
                <input type="password" id="password" class="form-control" placeholder="secret" value="secret">
            </div>
            <button class="btn btn-primary" onclick="doLogin()">Login</button>
        </div>
    </div>
    <div id="result" style="display:none;">
        <div class="card mb-3">
            <div class="card-header bg-success text-white">Token Received</div>
            <div class="card-body">
                <pre id="token" style="word-break:break-all;white-space:pre-wrap;color:#4ade80;background:#1e293b;padding:1rem;border-radius:0.5rem;"></pre>
            </div>
        </div>
        <div class="card mb-3">
            <div class="card-header">Token Payload (decoded)</div>
            <div class="card-body">
                <pre id="payload" style="color:#38bdf8;background:#1e293b;padding:1rem;border-radius:0.5rem;"></pre>
            </div>
        </div>
        <button class="btn btn-outline-info" onclick="verifyToken()">Verify Token</button>
        <span id="verify-result" class="ms-2"></span>
    </div>
    <div class="card bg-dark mt-4" style="border:1px solid #334155;">
        <div class="card-body">
            <h6 style="color:#e2e8f0;">How it works</h6>
            <pre style="background:#0f172a;color:#4ade80;padding:1rem;border-radius:0.5rem;font-size:0.8rem;"><code>auth = Auth()
token = auth.create_token({"username": "admin"})
payload = auth.get_payload(token)
is_valid = auth.validate_token(token)</code></pre>
        </div>
    </div>
</div>
<script>
var currentToken = '';
function doLogin() {
    fetch('/api/gallery/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            username: document.getElementById('username').value,
            password: document.getElementById('password').value
        })
    }).then(r => r.json()).then(d => {
        if (d.token) {
            currentToken = d.token;
            document.getElementById('token').textContent = d.token;
            try {
                var parts = d.token.split('.');
                var payload = JSON.parse(atob(parts[1]));
                document.getElementById('payload').textContent = JSON.stringify(payload, null, 2);
            } catch(e) {
                document.getElementById('payload').textContent = 'Could not decode';
            }
            document.getElementById('result').style.display = 'block';
            document.getElementById('verify-result').textContent = '';
        } else {
            alert(d.error || 'Login failed');
        }
    });
}
function verifyToken() {
    fetch('/api/gallery/auth/verify?token=' + encodeURIComponent(currentToken))
    .then(r => r.json()).then(d => {
        var el = document.getElementById('verify-result');
        if (d.valid) {
            el.innerHTML = '<span class="badge bg-success">Valid</span>';
        } else {
            el.innerHTML = '<span class="badge bg-danger">Invalid</span>';
        }
    });
}
</script>
</body></html>"""
    return response(html)


@noauth()
@post("/api/gallery/auth/login")
async def gallery_login(request, response):
    body = request.body or {}
    username = body.get("username", "")
    password = body.get("password", "")
    if username and password:
        auth = Auth()
        token = auth.create_token({"username": username, "role": "user"})
        return response({"token": token, "message": f"Welcome {username}!"})
    return response({"error": "Username and password required"}, 401)


@noauth()
@get("/api/gallery/auth/verify")
async def gallery_verify(request, response):
    token = request.params.get("token", "")
    auth = Auth()
    is_valid = auth.validate_token(token)
    return response({"valid": is_valid})
