import os
from tina4_python.Debug import Debug
from tina4_python.Router import post, get
from keycloak import KeycloakOpenID


@post("/login")
async def post_login(request, response):

    keycloak_openid = KeycloakOpenID(server_url=os.getenv("KEYCLOAK_URL", ""),
                                     client_id=os.getenv("KEYCLOAK_CLIENT_ID", "admin"),
                                     realm_name=os.getenv("KEYCLOAK_REALM", "production"),
                                     client_secret_key="secret")

    try:
        token = keycloak_openid.token(request.body["email"], request.body["password"])
        userinfo = keycloak_openid.userinfo(token['access_token'])
        Debug.info("Login success", userinfo)
    except Exception as e:
        Debug.error("Login failed", str(e))
        return response.redirect("/")

    request.session.set("userinfo", userinfo)
    return response.redirect("/dashboard")

@get("/dashboard")
async def dashboard(request, response):
    userinfo = request.session.get("userinfo")

    return response(userinfo)
