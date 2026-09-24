"""Compact records must retain per-operation diffs, undo, and legacy readability."""
import json, os, unittest
from unittest import mock
import test_sun as fixtures
from test_sun import sun, run, hook, write, read


class EventStorageTest(unittest.TestCase):
    setUp, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call

    def test_compact_squashed_operations_keep_their_own_diffs_and_undo(self):
        hook("UserPromptSubmit")
        inp = {"file_path": "a.txt", "content": "alpha\n"}
        hook("PreToolUse", tool_name="Write", tool_input=inp, tool_use_id="a")
        write("a.txt", "alpha\n")
        write("human.txt", "human\n")
        hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="a")
        self.tool_call("session12345", "b.txt", "beta\n", 1)
        hook("Stop")
        events = [e for e in sun.events() if e.get("snapshot")]
        self.assertEqual(len(events), 3)
        self.assertEqual({e["commit"] for e in events}, {self.sun_head()})
        self.assertEqual(len({e["snapshot"] for e in events}), 2)
        for event in events:
            stored = json.loads(self.git("cat-file", "blob", "refs/sun/events/" + event["id"]))
            self.assertNotIn("pr", stored)
            self.assertNotIn("parents", stored)
            for call in stored.get("tool_calls", []): self.assertNotIn("input", call)
            for edit in stored["edits"]:
                self.assertNotIn("patch", edit)
                self.assertNotIn("attribution", edit)
                self.assertIn("attribution_method", edit)
            materialized = sun.event_edits(event)
            self.assertEqual(len(materialized), 1)
            edit = materialized[0]
            content = {"a.txt": "alpha", "b.txt": "beta", "human.txt": "human"}[edit["file"]]
            self.assertIn("+" + content, edit["patch"])
            for other in {"alpha", "beta", "human"} - {content}:
                self.assertNotIn("+" + other, edit["patch"])
        first = next(e for e in events if e["edits"][0]["file"] == "a.txt")
        self.assertIn("+alpha", run("show", first["snapshot"]))
        exported = [json.loads(line) for line in run("export").splitlines()]
        agent = next(e for e in exported if e["session"])
        self.assertEqual({e["file"] for e in agent["edits"]}, {"a.txt", "b.txt"})
        self.assertNotIn("+human", str(agent["edits"]))
        run("undo", "--op", first["id"])
        self.assertFalse(os.path.exists("a.txt"))
        self.assertEqual(read("b.txt"), "beta\n")
        self.assertEqual(read("human.txt"), "human\n")

    def test_legacy_patch_and_nested_attribution_remain_readable(self):
        write("a.txt", "alpha\n")
        run("sync")
        event = sun.events()[-1]
        patch = sun.event_edits(event)[0]["patch"]
        event["edits"] = [{"file": "a.txt", "patch": patch,
                           "attribution": {"method": "sync"}}]
        self.git("update-ref", "refs/sun/events/" + event["id"], sun.blob(json.dumps(event)))
        legacy = sun.events()[-1]
        with mock.patch.object(sun, "git", side_effect=AssertionError("already has a patch")):
            self.assertEqual(sun.event_edits(legacy), [
                {"file": "a.txt", "patch": patch, "attribution_method": "sync"}])
        self.assertIn("attribution", legacy["edits"][0])
        self.assertIn("+alpha", run("show", event["commit"]))
        run("undo", "--op", event["id"])
        self.assertFalse(os.path.exists("a.txt"))

    def test_old_turn_offsets_load_into_clear_names_and_boolean(self):
        tp = os.path.join(self.proj, "chat.jsonl")
        first = '{"type":"user","message":{"content":"one"}}\n'
        second = '{"type":"user","message":{"content":"two"}}\n'
        write(tp, first + second)
        sun.save_state("turns.json", {"session12345": {
            "n": 1, "start": self.sun_head(), "branch": sun.shadow_ref(),
            "transcript": tp, "toffset": 0, "soffset": len(first.encode()), "seen": 2}})
        sun.prompt_boundary("session12345", {"transcript_path": tp})
        turn = sun.state("turns.json", {})["session12345"]
        self.assertEqual(turn["n"], 2)
        self.assertEqual(turn["transcript_offset"], len(first.encode()))
        self.assertEqual(turn["scan_offset"], len((first + second).encode()))
        self.assertIs(turn["prompt_seen"], True)
        self.assertFalse({"toffset", "soffset", "seen"} & turn.keys())
