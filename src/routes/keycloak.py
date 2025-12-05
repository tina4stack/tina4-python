import os
from keycloak import KeycloakOpenID
from tina4_python import description, example, tags, post, get, Debug, secure


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
        return response.redirect("/hello/world/test")

    request.session.set("userinfo", userinfo)
    return response.redirect("/dashboard")


@get("/dashboard")
@description("Moo")
async def dashboard(request, response):
    userinfo = request.session.get("userinfo")

    return response(userinfo)
