"""Real CLI integration cases shared with the inspectable experiment runner."""
from pathlib import Path
import tempfile
import unittest
from experiments.collaboration import Lab, SCENARIOS, many_users


class CollaborationTest(unittest.TestCase):
    def test_scenarios(self):
        for name, scenario in SCENARIOS.items():
            if name == "many-users":
                continue
            with self.subTest(scenario=name), tempfile.TemporaryDirectory() as root:
                scenario(Lab(Path(root) / name))

    def test_multiple_collaborators_and_schedules(self):
        for count in (3, 5, 10):
            for seed in (17, 41):
                with self.subTest(users=count, seed=seed), tempfile.TemporaryDirectory() as root:
                    many_users(Lab(Path(root) / "experiment", seed), count)


if __name__ == "__main__":
    unittest.main()
