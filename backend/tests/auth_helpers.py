from app.auth import issue_demo_token


def auth_headers(broker_id: str = "broker-a", actor: str = "test-user") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_demo_token(broker_id, actor)}"}
