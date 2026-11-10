from app.users import search_users


def handle_search(request, conn):
    """GET /users?q=<name>"""
    return {"users": search_users(conn, request.args["q"])}
