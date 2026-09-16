# AI-customer-support-agent\scripts\register_customer.py
import getpass
import http.cookiejar
import json
import urllib.error
import urllib.request

api = "http://localhost:8000"
origin = "http://localhost:5173"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

cookies = http.cookiejar.CookieJar()
client = urllib.request.build_opener(
    NoRedirect(),
    urllib.request.HTTPCookieProcessor(cookies),
)

email = input("Customer email: ").strip()
password = getpass.getpass("Customer password: ")
confirmation = getpass.getpass("Confirm password: ")

if password != confirmation:
    raise SystemExit("Passwords do not match. No request was sent.")

request = urllib.request.Request(
    api + "/v1/auth/register",
    data=json.dumps({
        "email": email,
        "password": password,
    }).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": origin,
    },
    method="POST",
)

try:
    with client.open(request, timeout=30) as response:
        authentication = json.load(response)
except urllib.error.HTTPError as error:
    status = error.code
    error.close()
    messages = {
        400: "Registration rejected by the password policy.",
        403: "Origin rejected. Check BROWSER_ALLOWED_ORIGINS.",
        409: "This email already exists. Try signing in.",
        422: "Registration fields failed validation.",
    }
    raise SystemExit(
        messages.get(
            status,
            f"Registration returned HTTP {status}. "
            "Check account state before retrying.",
        )
    ) from None
except Exception:
    raise SystemExit(
        "Registration could not be confirmed. "
        "Try signing in before registering again."
    ) from None

print("Registration succeeded.")

try:
    token = authentication["tokens"]["access_token"]
    logout = urllib.request.Request(
        api + "/v1/auth/logout",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "Origin": origin,
        },
        method="POST",
    )

    with client.open(logout, timeout=30) as response:
        confirmed = json.load(response).get("logged_out") is True

    print(
        "Temporary registration session signed out."
        if confirmed
        else "Temporary session sign-out was not confirmed."
    )
except Exception:
    print(
        "Account created, but temporary session sign-out "
        "was not confirmed."
    )
finally:
    cookies.clear()