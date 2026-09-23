"""Tests for the agent in agents/browser-driver.md. README.md tells how to run them."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agents" / "browser-driver.md"
SKILL = Path(__file__).with_name("SKILL.md")
# SKILL.md and the agent put the list of the human steps after this line.
HUMAN_STEPS_LINE = "Never do these steps yourself. Give them to the user:"
# The agent can only look at its browser and act in it. It gets no tool that runs code in
# the page, reads the network traffic, or closes the browser. It also gets no shell, file
# system, registry, clipboard, or program launcher, because a web page can try to give it
# orders. ToolSearch loads the MCP tools of this set when the session defers them.
ALLOWED_TOOLS = {
    "ToolSearch",
    *(
        f"mcp__plugin_deploy-handoff_browser__browser_{name}"
        for name in (
            "tabs",
            "navigate",
            "navigate_back",
            "snapshot",
            "find",
            "take_screenshot",
            "click",
            "hover",
            "drag",
            "type",
            "press_key",
            "fill_form",
            "select_option",
            "file_upload",
            "drop",
            "handle_dialog",
            "wait_for",
        )
    ),
    *(
        f"mcp__windows-mcp__{name}"
        for name in ("Snapshot", "Screenshot", "Click", "Type", "Shortcut", "Wait")
    ),
}


def front_matter(text: str) -> dict[str, str]:
    """Return the fields of the front matter of text that have their value on one line."""
    lines = text.splitlines()
    end = lines.index("---", 1) if lines[:1] == ["---"] else 0
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, colon, value = line.partition(":")
        if colon and key.isidentifier():
            fields[key] = value.strip()
    return fields


def human_steps(text: str) -> list[str]:
    """Return the items of the list after HUMAN_STEPS_LINE in text."""
    lines = text.splitlines()
    items: list[str] = []
    for line in lines[lines.index(HUMAN_STEPS_LINE) + 1 :]:
        if line.startswith("- "):
            items.append(line.removeprefix("- "))
        elif items or line.strip():
            break
    return items


class BrowserDriverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = AGENT.read_text(encoding="utf-8")
        self.skill = SKILL.read_text(encoding="utf-8")
        self.tools = {tool.strip() for tool in front_matter(self.agent)["tools"].split(",")}

    def test_skill_starts_the_agent_by_its_name(self) -> None:
        name = front_matter(self.agent)["name"]
        self.assertEqual(name, AGENT.stem)
        self.assertIn(f'subagent_type: "deploy-handoff:{name}"', self.skill)

    def test_has_only_browser_tools(self) -> None:
        self.assertEqual(self.tools - ALLOWED_TOOLS, set())

    def test_browser_tools_come_from_the_mcp_server_of_the_plugin(self) -> None:
        manifest = ROOT / ".claude-plugin" / "plugin.json"
        plugin = json.loads(manifest.read_text(encoding="utf-8"))["name"]
        servers = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        prefixes = tuple(f"mcp__plugin_{plugin}_{server}__" for server in servers)
        plugin_tools = {tool for tool in self.tools if tool.startswith("mcp__plugin_")}
        self.assertTrue(plugin_tools)
        self.assertEqual({tool for tool in plugin_tools if not tool.startswith(prefixes)}, set())

    def test_skill_and_agent_list_the_same_human_steps(self) -> None:
        steps = human_steps(self.agent)
        self.assertTrue(steps)
        self.assertEqual(steps, human_steps(self.skill))


if __name__ == "__main__":
    unittest.main()
