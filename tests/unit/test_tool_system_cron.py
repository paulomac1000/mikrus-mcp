from mikrus_mcp import tool_system


def test_cron_remove_forwards_server_selector(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_invoke(ctx, capability, arguments):
        captured["capability"] = capability
        captured["arguments"] = arguments
        return {"success": True, "data": {}}

    monkeypatch.setattr(tool_system, "_invoke", fake_invoke)

    class _Ctx:
        pass

    import asyncio

    result = asyncio.run(tool_system.cron_remove("backup", _Ctx(), server="b"))
    assert result["success"] is True
    assert captured["capability"] == "cron_remove"
    assert captured["arguments"] == {"server": "b", "profile_id": "backup"}
