"""Hook wiring and attribution for known and unfamiliar harness tools."""
import json, unittest
import test_sun as fixtures
from test_sun import hook, read_json, run, sun, write


class HarnessAdapterTest(unittest.TestCase):
    setUp, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call

    def test_install_and_remove_preserve_user_hooks_for_each_harness(self):
        for harness, path, command, specific in (
            ("claude", ".claude/settings.json", "sun hook", {"PostToolUseFailure"}),
            ("codex", ".codex/hooks.json", "sun hook --harness codex",
             {"SubagentStart", "SubagentStop", "Interrupt"}),
        ):
            with self.subTest(harness=harness):
                custom = {"type": "command", "command": "echo custom"}
                write(path, json.dumps({"keep": True, "hooks": {"Stop": [{"hooks": [custom]}]}}))
                sun.install_hooks(harness)
                sun.install_hooks(harness)
                cfg = read_json(path)
                expected = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                            "Stop", "SessionEnd"} | specific
                self.assertEqual(set(cfg["hooks"]), expected)
                self.assertEqual({k for k in cfg if k != "hooks"}, {"keep"})
                for groups in cfg["hooks"].values():
                    commands = [h["command"] for g in groups for h in g["hooks"]]
                    self.assertEqual(commands.count(command), 1)
                sun.remove_hooks(harness)
                self.assertEqual(read_json(path), {"keep": True, "hooks": {"Stop": [{"hooks": [custom]}]}})

    def test_unknown_tool_observes_all_files_without_claiming_authorship(self):
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness):
                args = dict(harness=harness, tool_name="CustomPlugin", tool_use_id="custom",
                            tool_input={"file_path": "README.md"})
                before = self.sun_head()
                hook("PreToolUse", **args)
                hook("PostToolUse", **args)
                self.assertEqual(self.sun_head(), before)
                hook("PreToolUse", **args)
                write("README.md", harness + " changed\n")
                write(harness + ".txt", "also changed\n")
                hook("PostToolUse", **args)
                ev = sun.events()[-1]
                self.assertEqual(ev["actor"], "unknown")
                self.assertEqual({e["file"] for e in ev["edits"]}, {"README.md", harness + ".txt"})
                self.assertEqual({e["attribution"]["method"] for e in ev["edits"]}, {"uncertain"})
                self.assertEqual(ev["tool_calls"][0]["tool"], "CustomPlugin")
                self.assertFalse(sun.state("active.json", {}))

    def test_read_capabilities_do_not_claim_concurrent_edits(self):
        for harness, tool in (("claude", "Read"), ("codex", "view_image")):
            with self.subTest(harness=harness):
                args = dict(harness=harness, tool_name=tool, tool_input={"file_path": "README.md"})
                hook("PreToolUse", **args)
                write("README.md", harness + " human\n")
                hook("PostToolUse", **args)
                self.assertEqual(sun.events()[-1]["actor"], sun.local())
                self.assertFalse(sun.events()[-1].get("tool_calls"))

    def test_unknown_raw_input_remains_inspectable(self):
        args = dict(harness="codex", tool_name="CustomPlugin", tool_input="generate files")
        hook("PreToolUse", **args)
        write("raw.txt", "generated\n")
        hook("PostToolUse", **args)
        ev = sun.events()[-1]
        self.assertEqual(ev["tool_calls"][0]["input"], {"input": "generate files"})
        self.assertEqual(ev["actor"], "unknown")
        self.assertIn("CustomPlugin", run("show", ev["commit"]))

    def test_codex_native_shell_and_patch_payloads(self):
        patch = "*** Begin Patch\n*** Add File: a.txt\n+a\n*** Add File: b.txt\n+b\n*** End Patch"
        for i, (tool, inp) in enumerate((("exec_command", {"cmd": "generator"}),
                                        ("apply_patch", patch), ("apply_patch", {"patch": patch}))):
            with self.subTest(tool=tool, payload=type(inp).__name__):
                args = dict(harness="codex", tool_name=tool, tool_input=inp, tool_use_id=str(i))
                hook("PreToolUse", **args)
                write("a.txt", str(i) + "a\n")
                write("b.txt", str(i) + "b\n")
                hook("PostToolUse", **args)
                ev = sun.events()[-1]
                self.assertEqual(ev["actor"], sun.agent("session12345", "codex"))
                self.assertEqual({e["file"] for e in ev["edits"]}, {"a.txt", "b.txt"})
                self.assertEqual({e["attribution"]["method"] for e in ev["edits"]}, {"hook"})

    def test_unknown_tool_cannot_lose_changes_to_another_pre_hook(self):
        args = dict(tool_name="CustomPlugin", tool_use_id="custom")
        hook("PreToolUse", "custom", **args)
        write("custom.txt", "custom\n")
        self.tool_call("writer", "writer.txt", "writer\n")
        hook("PostToolUse", "custom", **args)
        changes = [(ed["file"], ev["actor"]) for ev in sun.events() for ed in ev.get("edits", [])]
        self.assertEqual(changes, [("writer.txt", "unknown"), ("custom.txt", "unknown")])
        self.assertFalse(sun.state("active.json", {}))


if __name__ == "__main__":
    unittest.main()
