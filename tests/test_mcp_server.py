import importlib
import sys

import pytest

mcp_module=pytest.importorskip("mcp",reason="Install package dependencies to run live MCP protocol tests")
from mcp import Client


@pytest.mark.anyio
async def test_in_memory_server_handshake_and_profile_tool(tmp_path,monkeypatch):
    monkeypatch.setenv("CAREER_COMPASS_HOME",str(tmp_path))
    sys.modules.pop("career_compass_mcp.server",None)
    server=importlib.import_module("career_compass_mcp.server")
    async with Client(server.mcp) as client:
        tools=await client.list_tools()
        names={tool.name for tool in tools.tools}
        assert {"profile_get","profile_update","discover_jobs","source_search_queries","job_list","tailoring_brief","save_tailored_document"}<=names
        result=await client.call_tool("profile_get",{})
        options=result.structured_content["supported_options"]
        assert {language["code"] for language in options["languages"]}=={"en","fa","es","ar"}
        updated=await client.call_tool("profile_update",{"profile_json":'{"preferred_language":"Farsi","document_language":"job","work_arrangements":["hybrid"],"mobility_support":["relocation"]}'})
        assert updated.structured_content["preferred_language"]=="fa"
        result=await client.call_tool("profile_get",{})
        assert result.structured_content["profile"]["work_arrangements"]==["hybrid"]
        assert result.structured_content["profile"]["mobility_support"]==["relocation"]
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client


@pytest.mark.anyio
async def test_stdio_server_handshake(tmp_path):
    root=Path(__file__).resolve().parents[1]
    params=StdioServerParameters(
        command=sys.executable,
        args=["-m","career_compass_mcp"],
        env={**os.environ,"CAREER_COMPASS_HOME":str(tmp_path)},
        cwd=root,
    )
    async with stdio_client(params) as (read_stream,write_stream):
        async with ClientSession(read_stream,write_stream) as session:
            await session.initialize()
            result=await session.list_tools()
            names={tool.name for tool in result.tools}
            assert {"profile_get","profile_update","discover_jobs","job_list","save_tailored_document"}<=names
