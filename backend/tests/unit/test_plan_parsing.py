from agents.architect import extract_plan


def test_no_plan_block_returns_text_unchanged():
    text = "Sure, here are your S3 buckets: bucket-a, bucket-b."
    display_text, plan = extract_plan(text)
    assert display_text == text
    assert plan is None


def test_extracts_plan_and_strips_tags():
    text = (
        "I'll set up an EC2 instance for you.\n"
        '<nimbus-plan>\n{"explanation": "test", "plan": [{"step": 1, "action": "create"}]}\n</nimbus-plan>'
    )
    display_text, plan = extract_plan(text)
    assert "<nimbus-plan>" not in display_text
    assert "</nimbus-plan>" not in display_text
    assert display_text == "I'll set up an EC2 instance for you."
    assert plan == {"explanation": "test", "plan": [{"step": 1, "action": "create"}]}


def test_preserves_text_after_closing_tag():
    text = "Before.\n<nimbus-plan>\n{\"plan\": []}\n</nimbus-plan>\nAfter."
    display_text, plan = extract_plan(text)
    assert display_text == "Before.\nAfter."
    assert plan == {"plan": []}


def test_malformed_json_inside_tags_falls_back_to_raw_text():
    text = "Explanation.\n<nimbus-plan>\n{not valid json\n</nimbus-plan>"
    display_text, plan = extract_plan(text)
    assert plan is None
    assert display_text == text


def test_only_opening_tag_present_is_treated_as_no_plan():
    text = "Some text <nimbus-plan> but no closing tag"
    display_text, plan = extract_plan(text)
    assert plan is None
    assert display_text == text
