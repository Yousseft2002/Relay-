from accounts.auth import require_admin


def delete_account(user, account_id, db):
    """POST /admin/accounts/<id>/delete"""
    require_admin(user)
    db.delete("accounts", account_id)
    return {"deleted": account_id}
