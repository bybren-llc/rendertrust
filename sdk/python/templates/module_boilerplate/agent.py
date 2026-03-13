def run(payload: dict) -> dict:
    return {"result": payload.get("text", "").upper()}


if __name__ == "__main__":
    import sys
    import json

    print(json.dumps(run(json.load(sys.stdin))))
