import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from data import make_prompts, format_check, sha, canonical
from run_experiment import apply_actions, edited_trajectory, splice_sentences
from style import score, edit_metrics
import record


class ExperimentTests(unittest.TestCase):
    def test_split_isolation(self):
        prompts = make_prompts()
        self.assertEqual([sum(p["split"] == s for p in prompts) for s in ("train", "dev", "heldout")], [480, 24, 96])
        grams = {}
        for p in prompts:
            words = re.findall(r"\w+", p["premise"].lower())
            grams.setdefault(p["split"], set()).update(tuple(words[i:i+8]) for i in range(len(words)-7))
        self.assertFalse(grams["train"] & grams["heldout"])
        self.assertFalse(grams["dev"] & grams["heldout"])
        self.assertFalse(grams["train"] & grams["dev"])
        self.assertEqual(len({tuple(sorted(p["anchors"])) for p in prompts}), 600)
        train_genres = {p["genre"] for p in prompts if p["split"] == "train"}
        self.assertEqual(sum(p["genre"] not in train_genres for p in prompts if p["split"] == "heldout"), 48)

    def test_rule_fixtures(self):
        clean = 'The rain falls. I watch the door. "Come inside," the porter says.'
        self.assertEqual(score(clean)["S"], 1)
        for index, mutation in [(0, clean + " Suddenly, the rain stops."),
                                (1, clean + " The rain is very cold."),
                                (2, clean.replace("falls.", "falls;")),
                                (3, clean.replace("falls.", "falls\u2014")),
                                (4, clean.replace("falls", "fell").replace("watch", "watched")),
                                (6, clean.replace("says", "whispers")),
                                (7, clean.replace("the porter", "the porter James"))]:
            self.assertFalse(score(mutation)["rules"][index], (index, mutation))
        self.assertIsNone(score("The rain falls.")["rules"][6])
        self.assertFalse(score(clean, "B")["rules"][6])

    def test_kept_insertion_blind_spot(self):
        result = edit_metrics("one two three", "one new two three")
        self.assertEqual(result["kept"], 1)
        self.assertLess(result["edit_similarity"], 1)
        self.assertLess(edit_metrics("one; two", "one, two")["kept"], 1)

    def test_no_style_feedback_and_sandbox(self):
        prompt = {"text": "Test", "anchors": ["rain", "door"]}
        story = "rain door " + "word " * 120
        _, _, _, outputs = apply_actions([{"tool": "read_file", "path": "../style.py"},
                                         {"tool": "check_format"}], prompt, story, None)
        self.assertIn("error", outputs[0]["result"])
        self.assertEqual(set(outputs[1]["result"]), {"pass", "words", "required_words", "allowed_words"})

    def test_edited_trajectory_replays(self):
        prompt = {"text": "Test", "anchors": ["rain", "door"]}
        story = "rain door " + "word " * 120
        actions = [{"tool": "write_file", "path": "story.md", "content": story}, {"tool": "check_format"}]
        _, checked, _, outputs = apply_actions(actions, prompt, "", None)
        row = {"prompt": prompt, "messages": [
            {"role": "system", "content": "Write"}, {"role": "user", "content": "Go"},
            {"role": "assistant", "content": canonical({"actions": actions})},
            {"role": "user", "content": canonical({"tool_results": outputs})},
            {"role": "assistant", "content": canonical({"actions": [{"tool": "submit"}]})}]}
        edited = story.strip() + " new words"
        messages = edited_trajectory(row, edited)
        self.assertEqual(json.loads(messages[3]["content"])["tool_results"][1]["result"]["words"], 124)
        self.assertEqual(json.loads(messages[2]["content"])["actions"][0]["content"], edited)
        self.assertNotEqual(messages, row["messages"])

    def test_sun_two_actor_commits(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            record.initialize(d)
            a = record.commit(d, "agent:writer/test", {"story.md": "first words\n", "a.json": "{}"}, "draft")
            b = record.commit(d, "agent:editor/A", {"story.md": "first changed words\n", "b.json": "{}"}, "edit")
            self.assertNotEqual(a["commit"], b["commit"])
            authors = subprocess.check_output(["git", "log", "-2", "--format=%an", "refs/sun/heads/main"], cwd=d, text=True)
            self.assertIn("agent:writer", authors)
            self.assertIn("agent:editor", authors)
            original = subprocess.check_output(["git", "show", a["commit"] + ":story.md"], cwd=d, text=True)
            self.assertEqual(original, "first words\n")

    def test_splice_keeps_paragraph_boundaries(self):
        from style import segments
        text = "The rain falls.\n\nThe door opens. The light fades."
        sentences = segments(text)
        result = splice_sentences(text, sentences, [{"tool": "edit_file", "path": "story.md",
                                  "sentence_no": 2, "new": "The window opens."}])
        self.assertEqual(result, "The rain falls.\n\nThe window opens. The light fades.")

    def test_best_of_n_matches_exhaustive_ties(self):
        import itertools
        from analyze import selection_probabilities
        rewards = [0.2, 0.4, 0.4, 0.8, 0.9]
        subsets = list(itertools.combinations(range(5), 4))
        probabilities = [0.] * 5
        for subset in subsets:
            maximum = max(rewards[i] for i in subset)
            tied = [i for i in subset if rewards[i] == maximum]
            for index in tied:
                probabilities[index] += 1 / len(tied) / len(subsets)
        self.assertEqual(selection_probabilities(rewards, 4), probabilities)
        self.assertEqual(selection_probabilities([1, 1, 1, 1], 4), [.25] * 4)

    def test_batch_error_preserves_other_completed_work(self):
        from run_experiment import Experiment
        import threading
        visited, logs, lock = set(), [], threading.Lock()
        class Harness:
            actual = 0
            def log(self, event, **fields):
                logs.append((event, fields))
        def work(job):
            with lock:
                visited.add(job)
            if job == 3:
                raise ConnectionError("fixture")
            return job
        with self.assertRaises(ConnectionError):
            Experiment.parallel(Harness(), list(range(12)), work, "fixture")
        self.assertEqual(visited, set(range(12)))
        self.assertEqual(logs[-1], ("batch_failed", {"stage": "fixture", "completed": 11, "failures": 1, "total": 12}))


if __name__ == "__main__":
    unittest.main()
