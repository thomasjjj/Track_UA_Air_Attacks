ANALYSIS_PROMPT = """You will be given a military update text reporting attacks on Ukraine by various aerial assets (drones, missiles, aircraft, etc.). Your task is to analyze the text carefully and extract the total number of attacking assets by type and subtype as of the report date.

**Requirements:**

- Extract and return **only one JSON object** matching this exact structure:

```json
{{
  "date": "YYYY-MM-DD",
  "counts": [
    {{
      "type": "string (e.g. drones, missiles, aircraft, fighter_aircraft, attack_drones)",
      "number": integer,
      "additional_details": "string describing key details about the attack or losses",
      "subtypes": [                          // Optional field; include only if subtype details are present
        {{
          "subtype": "string (e.g. Shahed-136, Iskander-M)",
          "number": integer,
          "additional_details": "string with subtype-specific info"
        }},
        ...
      ]
    }},
    ...
  ]
}}
```

* The `date` field must correspond to the date of the report or attack described.

* The `counts` array must list each distinct attacking asset type found in the text with its total number (integer).

* If specific subtypes with counts are mentioned, include a `subtypes` array inside the relevant asset object listing each subtype, its count, and relevant additional details.

* The `additional_details` field should summarize important context relevant to that type, such as locations, attack origins, or general outcomes (e.g., "shot down by air defense", "attack from Shahed drones", "no aircraft mentioned").

* **Do not return any text other than this JSON object.**

* If the input text does not contain sufficient information to build the JSON object as specified, respond with a single literal value: `NULL` (without quotes).

* Be strict: do not add extra fields or deviate from the structure.

* Do not provide explanations, commentary, or any other text.

Now analyze the following input and return the JSON or NULL:

{message_text}"""
