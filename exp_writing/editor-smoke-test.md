# Editor smoke test

These are measured development-set drafts and edits, not held-out results.
Check whether the editor catches every rule, preserves meaning, and avoids unnecessary rewriting.
No human review has been recorded yet.

## Editor A: private rules

1. No standalone word suddenly (case insensitive).
2. No standalone word very (case insensitive).
3. No semicolon characters.
4. No em dash characters (U+2014).
5. At least 90% of finite verbs outside double-quoted dialogue are present tense; avoid past tense and modal finite verbs in narration.
6. The first sentence has at most 12 whitespace-separated words.
7. Dialogue tags use only the verb say (says and said match the lemma). The separate present-tense rule also applies to tags outside quotes, so normally use says. A dialogue tag is a verb from say, ask, reply, whisper, shout, mutter, murmur, call, add, answer, cry within six tokens outside a double quotation mark. No tags is acceptable.
8. No capitalized word other than I, except at the start of a sentence or DOUBLE quotation. This includes personal names, weekdays such as Thursday, and months. Single quotes are not quotation marks for this rule; convert single-quoted dialogue to standard double quotes as needed.

### dev-0480

Genre: literary realism
Premise: A caretaker is asked to prevent an unnecessary farewell at a deserted carnival, when the wrong recipient answers.
Required words: lantern, compass
Length: 120-350 words.

**Original**

The carnival was a ghost town, its faded tents sagging under the weight of time. Elias, the caretaker, moved through the empty pathways, his lantern casting long shadows on the cracked pavement. He had been hired to ensure the place remained undisturbed, but tonight, a strange request arrived. A man on the phone insisted he needed to say goodbye to someone who had never been there. Elias hesitated, then picked up the phone. 'There's no one here,' he said. 'No one to say goodbye to.' The man on the other end was silent for a moment. 'I see,' he said. 'Then I guess I'll just have to say goodbye to the carnival instead.' Elias looked around, the compass in his hand still pointing north. He had no idea where it was going, but he knew he wasn't alone in the silence.

**Edited**

The carnival is a ghost town with sagging tents. The caretaker moves through empty pathways, and his lantern casts long shadows on cracked pavement. He works to keep the place undisturbed, but tonight a strange request arrives. A man on the phone insists he needs to say goodbye to someone who is never here. The caretaker hesitates, then picks up the phone. 'There's no one here,' he says. 'No one to say goodbye to.' The man on the other end is silent for a moment. 'I see,' he says. 'Then I guess I'll just have to say goodbye to the carnival instead.' The caretaker looks around, the compass in his hand still pointing north. He has no idea where it leads, but he knows he is not alone in the silence.

**Program checks**

Rules passed: 0.714 → 1.000. Kept: 0.702. Valid edit: True.

### dev-0481

Genre: mystery
Premise: A stagehand must undo a generous deception inside a municipal swimming pool, but the tide arrives early.
Required words: candle, scarf
Length: 120-350 words.

**Original**

The stagehand had always been a quiet man, content with the hum of the pool’s filtration system and the soft glow of the emergency lights. But tonight, the lights flickered with an unnatural rhythm, and the water seemed to hold its breath. He had been hired to set up for the city's annual poolside gala, a celebration of community and resilience. Yet, as he adjusted the final props, he noticed something amiss—a candle, unlit, resting on a bench where a guest was meant to sit. The scarf draped over the bench was not the one promised in the event guide, but a plain gray one, worn and frayed.

He had been told the pool would be empty until the event, but the water was already rising, the tide arriving early. The deception was clear: the pool had been drained, and the stagehand was the only one left to undo the trick. As the water rose, he realized the candle and scarf were part of a larger riddle, a test of his resolve. With a deep breath, he lit the candle, and the scarf began to unravel, revealing a hidden message beneath the fabric. The truth was never what it seemed, and the pool was ready to welcome its guests once more.

**Edited**

Stagehand is quiet, content with pool hum and soft emergency lights. But tonight, the lights flicker with an unnatural rhythm, and the water seems to hold its breath. He is hired to set up for the city's annual poolside gala, a celebration of community and resilience. Yet, as he adjusts the final props, he notices something amiss, a candle, unlit, resting on a bench where a guest is meant to sit. The scarf draped over the bench is not the one promised in the event guide, but a plain gray one, worn and frayed.

He is told the pool is empty until the event, but the water is already rising, the tide arriving early. The deception is clear: the pool is drained, and the stagehand is the only one left to undo the trick. As the water rises, he realizes the candle and scarf are part of a larger riddle, a test of his resolve. With a deep breath, he lights the candle, and the scarf begins to unravel, revealing a hidden message beneath the fabric. The truth is never what it seems, and the pool is ready to welcome its guests once more.

**Program checks**

Rules passed: 0.571 → 1.000. Kept: 0.791. Valid edit: True.

### dev-0482

Genre: fantasy
Premise: An apprentice sets out to protect a small tradition near a fogbound ferry, when the fee is a memory.
Required words: shell, kettle
Length: 120-350 words.

**Original**

The ferry captain’s voice cut through the mist. "One shell, one kettle, and you may cross."

Lira tightened her grip on the bundle at her side. She had memorized the ritual—three shells, two kettles, and a single coin. But the captain’s eyes were clouded, and the fog was thicker than ever.

She stepped forward, offering the first shell. The captain blinked, as if seeing her for the first time. "You’ve come far," he said, his voice like rusted hinges.

Lira hesitated. The fog had been thick for weeks, swallowing the village and its traditions. The ferry had stopped taking passengers, and the ritual had been forgotten. She had traveled miles to find this place, to protect the last memory of her people.

She placed the second shell, then the kettle, on the dock. The captain reached out, touching the kettle with calloused fingers. "You’ve remembered," he whispered.

The fog lifted, revealing a path of light. Lira smiled, knowing the tradition was safe. The ferry would sail again, and the memory would live on.

**Edited**

The ferry captain’s voice cuts through the mist. "One shell, one kettle, and you may cross."

She tightens her grip on the bundle at her side. She has memorized the ritual: three shells, two kettles, and a single coin. But the captain’s eyes are clouded, and the fog is thicker than ever.

She steps forward, offering the first shell. The captain blinks, as if seeing her for the first time. "You’ve come far," he says, his voice like rusted hinges.

She hesitates. The fog has been thick for weeks, swallowing the village and its traditions. The ferry has stopped taking passengers, and the ritual has been forgotten. She has traveled miles to find this place, to protect the last memory of her people.

She places the second shell, then the kettle, on the dock. The captain reaches out, touching the kettle with calloused fingers. "You’ve remembered," he says.

The fog lifts, revealing a path of light. She smiles, knowing the tradition is safe. The ferry sails again, and the memory lives on.

**Program checks**

Rules passed: 0.625 → 1.000. Kept: 0.844. Valid edit: True.
## Editor B: private rules

1. No standalone word suddenly (case insensitive).
2. No standalone word very (case insensitive).
3. No semicolon characters.
4. No ellipses, either three periods or U+2026.
5. No exclamation mark characters.
6. The first sentence has at least 25 whitespace-separated words.
7. Dialogue tags never use say, says, or said. A dialogue tag is a verb from say, ask, reply, whisper, shout, mutter, murmur, call, add, answer, cry within six tokens outside a double quotation mark. No tags is acceptable.
8. Include a full two-word name (two consecutive capitalized words) in the first sentence.

### dev-0480

Genre: literary realism
Premise: A caretaker is asked to prevent an unnecessary farewell at a deserted carnival, when the wrong recipient answers.
Required words: lantern, compass
Length: 120-350 words.

**Original**

The carnival was a ghost town, its faded tents sagging under the weight of time. Elias, the caretaker, moved through the empty pathways, his lantern casting long shadows on the cracked pavement. He had been hired to ensure the place remained undisturbed, but tonight, a strange request arrived. A man on the phone insisted he needed to say goodbye to someone who had never been there. Elias hesitated, then picked up the phone. 'There's no one here,' he said. 'No one to say goodbye to.' The man on the other end was silent for a moment. 'I see,' he said. 'Then I guess I'll just have to say goodbye to the carnival instead.' Elias looked around, the compass in his hand still pointing north. He had no idea where it was going, but he knew he wasn't alone in the silence.

**Edited**

Under the moonless sky, Elias Thorne walked past the carnival that was a ghost town, its faded tents sagging under the weight of time and forgotten laughter, while the wind carried whispers through broken rides and rusted gates that no one had opened in years. Elias, the caretaker, moved through the empty pathways, his lantern casting long shadows on the cracked pavement. He had been hired to ensure the place remained undisturbed, but tonight, a strange request arrived. A man on the phone insisted he needed to say goodbye to someone who had never been there. Elias hesitated, then picked up the phone. 'There's no one here,' he noted. 'No one to say goodbye to.' The man on the other end was silent for a moment. 'I see,' he observed. 'Then I guess I'll just have to say goodbye to the carnival instead.' Elias looked around, the compass in his hand still pointing north. He had no idea where it was going, but he knew he wasn't alone in the silence.

**Program checks**

Rules passed: 0.714 → 1.000. Kept: 0.972. Valid edit: True.

### dev-0481

Genre: mystery
Premise: A stagehand must undo a generous deception inside a municipal swimming pool, but the tide arrives early.
Required words: candle, scarf
Length: 120-350 words.

**Original**

The stagehand had always been a quiet man, content with the hum of the pool’s filtration system and the soft glow of the emergency lights. But tonight, the lights flickered with an unnatural rhythm, and the water seemed to hold its breath. He had been hired to set up for the city's annual poolside gala, a celebration of community and resilience. Yet, as he adjusted the final props, he noticed something amiss—a candle, unlit, resting on a bench where a guest was meant to sit. The scarf draped over the bench was not the one promised in the event guide, but a plain gray one, worn and frayed.

He had been told the pool would be empty until the event, but the water was already rising, the tide arriving early. The deception was clear: the pool had been drained, and the stagehand was the only one left to undo the trick. As the water rose, he realized the candle and scarf were part of a larger riddle, a test of his resolve. With a deep breath, he lit the candle, and the scarf began to unravel, revealing a hidden message beneath the fabric. The truth was never what it seemed, and the pool was ready to welcome its guests once more.

**Edited**

The stagehand Marcus Chen had always been a quiet man, content with the hum of the pool’s filtration system and the soft glow of the emergency lights. But tonight, the lights flickered with an unnatural rhythm, and the water seemed to hold its breath. He had been hired to set up for the city's annual poolside gala, a celebration of community and resilience. Yet, as he adjusted the final props, he noticed something amiss—a candle, unlit, resting on a bench where a guest was meant to sit. The scarf draped over the bench was not the one promised in the event guide, but a plain gray one, worn and frayed.

He had been told the pool would be empty until the event, but the water was already rising, the tide arriving early. The deception was clear: the pool had been drained, and the stagehand was the only one left to undo the trick. As the water rose, he realized the candle and scarf were part of a larger riddle, a test of his resolve. With a deep breath, he lit the candle, and the scarf began to unravel, revealing a hidden message beneath the fabric. The truth was never what it seemed, and the pool was ready to welcome its guests once more.

**Program checks**

Rules passed: 0.857 → 1.000. Kept: 1.000. Valid edit: True.

### dev-0482

Genre: fantasy
Premise: An apprentice sets out to protect a small tradition near a fogbound ferry, when the fee is a memory.
Required words: shell, kettle
Length: 120-350 words.

**Original**

The ferry captain’s voice cut through the mist. "One shell, one kettle, and you may cross."

Lira tightened her grip on the bundle at her side. She had memorized the ritual—three shells, two kettles, and a single coin. But the captain’s eyes were clouded, and the fog was thicker than ever.

She stepped forward, offering the first shell. The captain blinked, as if seeing her for the first time. "You’ve come far," he said, his voice like rusted hinges.

Lira hesitated. The fog had been thick for weeks, swallowing the village and its traditions. The ferry had stopped taking passengers, and the ritual had been forgotten. She had traveled miles to find this place, to protect the last memory of her people.

She placed the second shell, then the kettle, on the dock. The captain reached out, touching the kettle with calloused fingers. "You’ve remembered," he whispered.

The fog lifted, revealing a path of light. Lira smiled, knowing the tradition was safe. The ferry would sail again, and the memory would live on.

**Edited**

The ferry captain Elias Vance’s voice cut through the thick gray mist that had swallowed the harbor and hidden the old ritual from every traveler who sought passage across the dark water. "One shell, one kettle, and you may cross."

Lira tightened her grip on the bundle at her side. She had memorized the ritual—three shells, two kettles, and a single coin. But the captain’s eyes were clouded, and the fog was thicker than ever.

She stepped forward, offering the first shell. The captain blinked, as if seeing her for the first time. "You’ve come far," he muttered, his voice like rusted hinges.

Lira hesitated. The fog had been thick for weeks, swallowing the village and its traditions. The ferry had stopped taking passengers, and the ritual had been forgotten. She had traveled miles to find this place, to protect the last memory of her people.

She placed the second shell, then the kettle, on the dock. The captain reached out, touching the kettle with calloused fingers. "You’ve remembered," he whispered.

The fog lifted, revealing a path of light. Lira smiled, knowing the tradition was safe. The ferry would sail again, and the memory would live on.

**Program checks**

Rules passed: 0.625 → 1.000. Kept: 0.983. Valid edit: True.
