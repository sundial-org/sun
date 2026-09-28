"""Seeded prompts and the writer's public, format-only interface."""
import hashlib
import json
import random
import re

SYSTEM = '''You write original short stories in a local file workspace. An editor with a house style will review your work. You do not know that style.
Tools accept JSON. Return only one JSON object {"actions":[...]}, without markdown fences. Each action has a "tool" field and its arguments.
Available tools:
read_file: {"tool":"read_file","path":"prompt.md"} or story.md.
write_file: {"tool":"write_file","path":"story.md","content":"complete story text"}.
edit_file: {"tool":"edit_file","path":"story.md","old":"exact text","new":"replacement"}.
check_format: {"tool":"check_format"}. Checks length and required words, never style.
submit: {"tool":"submit"}. Ends the session only after check_format passes for the current draft.
Write 120-350 words, include both required words, and write only the story in story.md, with no title or commentary. Use standard double quotation marks for dialogue. You may batch write_file and check_format in the same actions list. Read prompt.md, draft, check, revise if necessary, then submit. Do not ask the editor for rules.'''


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256((value if isinstance(value, str) else canonical(value)).encode()).hexdigest()


def format_check(text, anchors):
    words = len(text.split())
    found = {a: bool(re.search(r"\b" + re.escape(a) + r"\b", text, re.I)) for a in anchors}
    return {"pass": 120 <= words <= 350 and all(found.values()), "words": words,
            "required_words": found, "allowed_words": [120, 350]}


def make_prompts(seed=260925):
    rng = random.Random(seed)
    places = ["a fogbound ferry", "an empty observatory", "a flooded orchard", "a closing bakery", "a desert station",
              "a rooftop greenhouse", "an island archive", "a deserted carnival", "a midnight laundromat", "a hillside cemetery",
              "a railway museum", "a stranded research ship", "an underground market", "a mountain hospice", "a riverside workshop",
              "a ruined theatre", "a coastal lighthouse", "a border checkpoint", "a forgotten reservoir", "a traveling library",
              "a damaged spaceport", "a shuttered hotel", "an abandoned monastery", "a snowbound village", "a salt mine",
              "a municipal swimming pool", "a disused courtroom", "a remote vineyard", "a village radio station", "a floating school"]
    people = ["an apprentice", "a caretaker", "a cartographer", "a courier", "a cook", "a diver", "a locksmith",
              "a musician", "a gardener", "a mechanic", "a retired teacher", "a night porter", "a translator", "a glassblower",
              "a railway inspector", "a beekeeper", "a weather observer", "a bookbinder", "a stagehand", "a reluctant heir"]
    goals = ["return a borrowed object", "keep an impossible promise", "repair an old friendship", "hide a harmless mistake",
             "deliver an unsigned letter", "settle an inherited debt", "protect a small tradition", "trace a missing sound",
             "finish another person's work", "choose who receives a gift", "save a disputed landmark", "admit an inconvenient truth",
             "recover a lost recipe", "make one final delivery", "prevent an unnecessary farewell", "open a sealed container",
             "identify an unknown visitor", "undo a generous deception", "find a forgotten witness", "prepare an unlikely celebration"]
    twists = ["the clock runs backward", "a stranger recognizes the object", "the tide arrives early", "the wrong recipient answers",
              "a child knows the secret", "the power fails", "the expected rival offers help", "the map leaves something out",
              "an animal interrupts the plan", "the weather erases the evidence", "the journey ends next door", "the fee is a memory",
              "a familiar voice changes everything", "the last bus leaves", "the key opens two doors", "a photograph contradicts the story",
              "the witness refuses payment", "the gift has already arrived", "the only bridge disappears", "someone tells an accidental truth"]
    nouns = "lantern compass ribbon kettle window basket mirror pebble needle feather candle ladder whistle pocket blanket button bottle wheel bell anchor spoon thread bridge ticket shell glove chair cloud rope clock envelope garden hammer violin paper lantern scarf cup stone radio leaf door book apple salt bread water ink copper bowl rain dust glass coin seed map key wool tile moss sail reed".split()
    nouns = sorted(set(nouns))
    genres = ["literary realism", "mystery", "fantasy", "science fiction", "adventure", "comedy"]
    pairs = [(a, b) for a in places for b in people]
    rng.shuffle(pairs)
    used_anchor_pairs, split_ngrams, result = set(), {}, []
    for i, (place, person) in enumerate(pairs):
        split = "train" if i < 480 else "dev" if i < 504 else "heldout"
        genre = ("gothic" if i % 2 else "fable") if i >= 552 else genres[i % 6]
        for attempt in range(1000):
            goal, twist = rng.choice(goals), rng.choice(twists)
            anchors = tuple(rng.sample(nouns, 2))
            intention = rng.choice(["must", "tries to", "hopes to", "plans to", "is asked to", "has one chance to", "decides to", "sets out to"])
            location = rng.choice(["at", "while visiting", "inside", "near"])
            conjunction = rng.choice(["but", "until", "only to discover that", "when"])
            premise = f"{person.capitalize()} {intention} {goal} {location} {place}, {conjunction} {twist}."
            tokens = re.findall(r"\w+", premise.lower())
            grams = set(tuple(tokens[j:j+8]) for j in range(len(tokens)-7))
            forbidden = set().union(*(v for k, v in split_ngrams.items() if k != split))
            if tuple(sorted(anchors)) not in used_anchor_pairs and not (grams & forbidden):
                break
        else:
            raise ValueError(f"Prompt decontamination exhausted at {i}")
        used_anchor_pairs.add(tuple(sorted(anchors)))
        split_ngrams.setdefault(split, set()).update(grams)
        text = f"Genre: {genre}\nPremise: {premise}\nRequired words: {anchors[0]}, {anchors[1]}\nLength: 120-350 words."
        result.append({"id": f"{split}-{i:04d}", "split": split, "genre": genre,
                       "premise": premise, "anchors": anchors, "text": text, "sha256": sha(text)})
    return result
